import os
import re
import logging
import requests
import tiktoken
import asyncio
from io import BytesIO
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, HumanMessage

from langchain_pymupdf4llm.pymupdf4llm_loader import PyMuPDF4LLMLoader
from langchain_docling.loader import DoclingLoader, ExportType
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language
from langchain_core.documents import Document

from vector_store import get_vector_store
from dotenv import load_dotenv

load_dotenv()


# Custom Exceptions
class DocumentProcessingError(Exception):
    """Base exception for document processing errors"""

    pass


class SummaryGenerationError(DocumentProcessingError):
    """Exception raised when summary generation fails"""

    pass


class DocumentLoadError(DocumentProcessingError):
    """Exception raised when document loading fails"""

    pass


class InvalidURLError(DocumentProcessingError):
    """Exception raised when URL validation fails"""

    pass


def _get_openrouter_api_key() -> str:
    """Lazy load API key to avoid exposure in module scope"""
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise ValueError(
            "OPENROUTER_API_KEY not configured. Set it in your environment."
        )
    return key


def get_summarizer_model():
    """Initialize summarization model with lazy-loaded API key"""
    summarizer = init_chat_model(
        model="x-ai/grok-4-fast",
        model_provider="openai",
        api_key=_get_openrouter_api_key(),
        base_url="https://openrouter.ai/api/v1",
        temperature=0.1,
        max_tokens=1024,
        timeout=120,
    )
    return summarizer


logger = logging.getLogger(__name__)


class DocumentProcessor:
    # Token thresholds
    SMALL_SUMMARY_THRESHOLD = 500  # Documents smaller than this skip LLM summarization
    EMBED_WHOLE_THRESHOLD = 1000  # Below this: embed whole, don't chunk if small
    EMBEDDING_MODEL_LIMIT = 8191  # Safety check: text-embedding-3-small/large limit
    MAX_SUMMARY_TOKENS = 20000  # Summary truncation limit

    # TODO: Confirmation for using ALLOWED_S3_DOMAINS
    # Rate limiting
    MAX_CONCURRENT_SUMMARIES = 20  # Maximum concurrent LLM calls
    SUMMARY_TIMEOUT = 120  # Timeout for summary generation (seconds)

    # Security - Allowed S3 URL patterns (flexible pattern matching)
    # Supports multiple S3 URL formats:
    # - https://bucket.s3.amazonaws.com/key
    # - https://bucket.s3-region.amazonaws.com/key
    # - https://s3.region.amazonaws.com/bucket/key
    ALLOWED_S3_PATTERNS = [
        r".*\.s3\.amazonaws\.com$",  # bucket.s3.amazonaws.com
        r".*\.s3-[a-z0-9-]+\.amazonaws\.com$",  # bucket.s3-region.amazonaws.com
        r"^s3\.[a-z0-9-]+\.amazonaws\.com$",  # s3.region.amazonaws.com
        r"^s3\.amazonaws\.com$",  # s3.amazonaws.com (legacy)
    ]

    LANG_MAP = {
        # Documents
        ".md": Language.MARKDOWN,
        ".markdown": Language.MARKDOWN,
        ".rst": Language.RST,
        ".latex": Language.LATEX,
        ".tex": Language.LATEX,
        ".html": Language.HTML,
        # Python
        ".py": Language.PYTHON,
        # JavaScript/TypeScript
        ".js": Language.JS,
        ".jsx": Language.JS,
        ".ts": Language.TS,
        ".tsx": Language.TS,
        # C Family
        ".c": Language.C,
        ".cpp": Language.CPP,
        ".h": Language.CPP,
        ".hpp": Language.CPP,
        ".cs": Language.CSHARP,
        # JVM Languages
        ".java": Language.JAVA,
        ".kt": Language.KOTLIN,
        ".kts": Language.KOTLIN,
        ".scala": Language.SCALA,
        # Web/Mobile
        ".php": Language.PHP,
        ".swift": Language.SWIFT,
        # Systems
        ".go": Language.GO,
        ".rs": Language.RUST,
        ".rb": Language.RUBY,
        # Scripting
        ".lua": Language.LUA,
        ".pl": Language.PERL,
        ".ps1": Language.POWERSHELL,
        # Functional
        ".hs": Language.HASKELL,
        ".ex": Language.ELIXIR,
        ".exs": Language.ELIXIR,
        # Blockchain/Proto
        ".proto": Language.PROTO,
        ".sol": Language.SOL,
        # Legacy
        ".cobol": Language.COBOL,
        ".cob": Language.COBOL,
        ".vb": Language.VISUALBASIC6,
    }

    FILE_CONFIGS = {
        ".pdf": {"loader": "pymupdf4llm", "chunk_size": 1000, "chunk_overlap": 200},
        # DoclingLoader(URLs)
        ".docx": {"loader": "docling", "chunk_size": 1000, "chunk_overlap": 200},
        ".xlsx": {"loader": "docling", "chunk_size": 1000, "chunk_overlap": 200},
        ".pptx": {"loader": "docling", "chunk_size": 1000, "chunk_overlap": 200},
        ".csv": {"loader": "docling", "chunk_size": 1000, "chunk_overlap": 200},
        # Documents (Language-aware!)
        ".md": {"loader": "docling", "chunk_size": 1000, "chunk_overlap": 200},
        ".html": {"loader": "docling", "chunk_size": 1200, "chunk_overlap": 150},
        ".htm": {"loader": "docling", "chunk_size": 1200, "chunk_overlap": 150},
        ".rst": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".txt": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        # Code (Language-aware! Larger chunks for context)
        ".py": {"loader": "text", "chunk_size": 1500, "chunk_overlap": 200},
        ".js": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".ts": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".tsx": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".jsx": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".java": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".go": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".rs": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".cpp": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".c": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".rb": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 150},
        ".php": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".swift": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".kt": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".scala": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
    }

    def __init__(self):
        """
        Initialize DocumentProcessor with vector store, tokenizer, and summarizer.
        Includes rate limiting and security configurations.
        """
        self.vector_store = get_vector_store("document")
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        self.summarizer = get_summarizer_model()
        self.summary_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_SUMMARIES)
        logger.info("DocumentProcessor initialized with security and rate limiting")

    def _count_tokens(self, content: str) -> int:
        """
        Count tokens in text using tiktoken encoder.

        Args:
            content: Text content to count tokens for

        Returns:
            Number of tokens in the content

        Note:
            Uses cl100k_base encoding (GPT-3.5/GPT-4 tokenizer)
        """
        return len(self.tokenizer.encode(content))

    # TODO: This is also Not confirmed _validate_s3_url
    def _validate_s3_url(self, url: str) -> None:
        """
        Validate S3 URL to prevent SSRF attacks using pattern matching.
        Supports multiple S3 URL formats including bucket-specific and regional URLs.

        Args:
            url: The URL to validate

        Raises:
            InvalidURLError: If URL is invalid or not from allowed S3 domain
        """
        try:
            parsed = urlparse(url)

            # Check scheme
            if parsed.scheme not in ["https", "http"]:
                raise InvalidURLError(
                    f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed."
                )

            # Check if domain is in whitelist
            hostname = parsed.hostname
            if not hostname:
                raise InvalidURLError("URL has no hostname")

            # Check against regex patterns
            is_allowed = any(
                re.match(pattern, hostname) for pattern in self.ALLOWED_S3_PATTERNS
            )

            if not is_allowed:
                raise InvalidURLError(
                    f"URL domain '{hostname}' doesn't match allowed S3 patterns. "
                    f"Valid formats: bucket.s3.amazonaws.com, bucket.s3-region.amazonaws.com, "
                    f"s3.region.amazonaws.com"
                )

            logger.debug(f"URL validation passed: {hostname}")

        except InvalidURLError:
            raise
        except Exception as e:
            raise InvalidURLError(f"URL validation failed: {e}")

    def _should_chunk_document(self, text: str, file_ext: str) -> Dict[str, Any]:
        """
        Determine if document should be chunked based on size.

        Args:
            text: Full document text
            file_ext: File extension (e.g., '.py', '.pdf')

        Returns:
            Dictionary containing:
                - should_chunk (bool): Whether to chunk the document
                - reason (str): Reason for the decision
                - token_count (int): Total tokens in document
                - char_count (int): Total characters in document
                - strategy (str): Chunking strategy to use
                - message (str): Human-readable decision message

        Note:
            Documents below EMBED_WHOLE_THRESHOLD (1000 tokens) are embedded whole
        """
        token_count = self._count_tokens(text)
        char_count = len(text)

        if token_count < self.EMBED_WHOLE_THRESHOLD:
            return {
                "should_chunk": False,
                "reason": "small_file",
                "token_count": token_count,
                "char_count": char_count,
                "strategy": "embed_whole",
                "message": f"Small ({token_count}t < {self.EMBED_WHOLE_THRESHOLD}t), embed whole",
            }
        else:
            return {
                "should_chunk": True,
                "reason": "large_or_medium_file",
                "token_count": token_count,
                "char_count": char_count,
                "strategy": "standard_chunking",
                "message": f"File ({token_count}t) chunked with standard strategy",
            }

    async def generate_document_summary(
        self, full_text: str, filename: str, file_ext: str
    ) -> str:
        """
        Generate document summary with rate limiting and timeout.

        Args:
            full_text: Complete document text
            filename: Name of the file
            file_ext: File extension

        Returns:
            Summary text

        Raises:
            SummaryGenerationError: If summary generation fails
        """
        async with self.summary_semaphore:
            token_count = self._count_tokens(full_text)

            # If document is small enough, use it as-is without summarization
            if token_count < self.SMALL_SUMMARY_THRESHOLD:
                logger.info(
                    f"Document {filename} is small ({token_count}t < {self.SMALL_SUMMARY_THRESHOLD}t), "
                    f"using full text as summary"
                )
                return full_text

            # Truncate if needed
            if token_count > self.MAX_SUMMARY_TOKENS:
                logger.info(
                    f"Truncating {filename}: {token_count}t -> {self.MAX_SUMMARY_TOKENS}t"
                )
                encoded = self.tokenizer.encode(full_text)
                truncated_text = self.tokenizer.decode(
                    encoded[: self.MAX_SUMMARY_TOKENS]
                )
                summarization_text = truncated_text
                actual_tokens = self.MAX_SUMMARY_TOKENS
            else:
                summarization_text = full_text
                actual_tokens = token_count

            is_code = file_ext.lower() in self.LANG_MAP
            content_type = "code file" if is_code else "document"
            language = self.LANG_MAP.get(file_ext.lower()).value if is_code else "text"

            try:
                system_prompt = f"""You are an expert document summarizer. Create a concise, informative summary of this {content_type}.

For code files: Focus on main functions, classes, logic flow, and key features.
For documents: Focus on main topics, key points, structure, and conclusions.

Keep the summary under 500 words but capture all essential information."""

                user_prompt = f"""Summarize this {content_type} ({language}):

Filename: {filename}
Token Count: {actual_tokens}

Content:
{summarization_text}

Provide a clear, structured summary."""

                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]

                # Add timeout protection
                response = await asyncio.wait_for(
                    self.summarizer.ainvoke(messages), timeout=self.SUMMARY_TIMEOUT
                )
                summary = response.content.strip()

                logger.info(f"Summary generated for {filename}: {len(summary)} chars")
                return summary

            except asyncio.TimeoutError:
                error_msg = f"Summary generation timed out after {self.SUMMARY_TIMEOUT}s for {filename}"
                logger.error(error_msg, exc_info=True)
                raise SummaryGenerationError(error_msg)

            except Exception as e:
                error_msg = f"Summary generation failed for {filename}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise SummaryGenerationError(error_msg)

    def _load_documents(
        self, s3_url: str, file_ext: str, filename: str
    ) -> List[Document]:
        """
        Load documents from S3 URL with validation and fallback chain.

        Args:
            s3_url: S3 URL to load from
            file_ext: File extension
            filename: Original filename

        Returns:
            List of Document objects

        Raises:
            DocumentLoadError: If all loaders fail
        """
        # Validate URL before any loading
        # TODO: Re-enable after adding DigitalOcean Spaces domains to ALLOWED_S3_PATTERNS
        # self._validate_s3_url(s3_url)

        config = self.FILE_CONFIGS.get(
            file_ext.lower(), {"loader": "text", "chunk_size": 1000}
        )
        loader_type = config["loader"]

        if loader_type == "pymupdf4llm":
            try:
                logger.info(f"Loading PDF with PyMuPDF4LLMLoader: {filename}")
                loader = PyMuPDF4LLMLoader(s3_url, extract_images=False)
                return loader.load()
            except Exception as e:
                logger.warning(f"PyMuPDF4LLM failed, PyMuPDFLoader fallback: {e}")
                try:
                    logger.info(f"PDF fallback: PyMuPDFLoader: {filename}")
                    loader = PyMuPDFLoader(s3_url, mode="page")
                    return loader.load()
                except Exception as e2:
                    logger.error(f"Both PDF loaders failed: {e2}")
                    return self._text_fallback(s3_url, filename)

        elif loader_type == "docling":
            try:
                logger.info(f"Loading with DoclingLoader: {filename}")
                loader = DoclingLoader(
                    file_path=s3_url,
                    export_type=ExportType.DOC_CHUNKS,
                    chunker_type="hybrid",
                    ocr_enabled=False,
                )
                return loader.load()
            except Exception as e:
                logger.warning(f"Docling failed, text fallback: {e}")
                return self._text_fallback(s3_url, filename)
        else:
            logger.info(f"Text/Code loader: {filename}")
            return self._text_fallback(s3_url, filename)

    def _text_fallback(self, s3_url: str, filename: str) -> List[Document]:
        """
        Universal text fallback loader with security validation.

        Args:
            s3_url: Pre-validated S3 URL
            filename: Original filename

        Returns:
            List containing single Document
        """
        try:
            # URL already validated in _load_documents, but double-check for direct calls
            # TODO: Re-enable after adding DigitalOcean Spaces domains to ALLOWED_S3_PATTERNS
            # self._validate_s3_url(s3_url)

            resp = requests.get(s3_url, timeout=60, stream=True)
            resp.raise_for_status()
            text = BytesIO(resp.content).read().decode("utf-8", errors="ignore")

            logger.info(f"Text fallback successful: {filename} ({len(text)} chars)")
            return [Document(page_content=text, metadata={"source": filename})]

        # except InvalidURLError:
        #     # Re-raise security errors immediately
        #     raise
        except Exception as e:
            error_msg = f"Text fallback failed for {filename}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise DocumentLoadError(error_msg)

    def _validate_chunks(self, chunks: List[Document]) -> List[Document]:
        """
        Validate and track chunk quality metrics.

        Args:
            chunks: List of document chunks to validate

        Returns:
            Filtered list of chunks with empty chunks removed

        Note:
            Logs statistics including:
            - empty_chunks: Count of completely empty chunks
            - very_small_chunks: Chunks with < 50 characters
            - avg_chunk_size: Average chunk size in characters
            - max_chunk_size: Largest chunk size
        """
        stats = {
            "empty_chunks": 0,
            "very_small_chunks": 0,
            "avg_chunk_size": 0,
            "max_chunk_size": 0,
        }

        sizes = []
        for chunk in chunks:
            content_len = len(chunk.page_content)
            sizes.append(content_len)

            if content_len == 0:
                stats["empty_chunks"] += 1
            elif content_len < 50:
                stats["very_small_chunks"] += 1

        if sizes:
            stats["avg_chunk_size"] = sum(sizes) / len(sizes)
            stats["max_chunk_size"] = max(sizes)

        logger.info(f"Chunk stats: {stats}")

        # Filter out empty chunks
        return [c for c in chunks if c.page_content.strip()]

    def _chunk_documents(
        self, docs: List[Document], file_ext: str, strategy: str
    ) -> List[Document]:
        """
        Smart language-aware chunking with token-based splitting.

        Args:
            docs: List of documents to chunk
            file_ext: File extension for language detection
            strategy: Chunking strategy name (for logging)

        Returns:
            List of chunked documents with metadata

        Note:
            - Uses language-specific splitters for 41+ programming languages
            - Applies token-based counting for accurate size limits
            - Validates overlap ratio (warns if < 10% or > 50%)
            - Adds chunk_index, total_chunks, and chunk_token_count to metadata
            - Falls back to simple chunking on errors
        """
        try:
            # Get configuration for this file type
            config = self.FILE_CONFIGS.get(
                file_ext.lower(), {"chunk_size": 1000, "chunk_overlap": 200}
            )
            chunk_size = config.get("chunk_size", 1000)
            chunk_overlap = config.get("chunk_overlap", 200)

            # Validate overlap ratio
            overlap_ratio = chunk_overlap / chunk_size
            if overlap_ratio < 0.1 or overlap_ratio > 0.5:
                logger.warning(f"Overlap ratio {overlap_ratio:.1%} may be suboptimal")

            # Language-aware splitting
            lang = self.LANG_MAP.get(file_ext.lower())

            if lang:
                logger.info(f"Using {lang.value}-aware splitter with token counting")
                text_splitter = RecursiveCharacterTextSplitter.from_language(
                    language=lang,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    length_function=self._count_tokens,
                )
            else:
                logger.info(f"Using generic splitter with token counting")
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    length_function=self._count_tokens,
                )

            chunks = text_splitter.split_documents(docs)

            # Add chunk metadata with token count
            for i, chunk in enumerate(chunks):
                chunk.metadata.update(
                    {
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "is_whole_document": False,
                        "chunk_token_count": self._count_tokens(chunk.page_content),
                    }
                )

            # Validate chunks
            chunks = self._validate_chunks(chunks)

            logger.info(f"Created {len(chunks)} chunks ({strategy})")
            return chunks

        except Exception as e:
            logger.error(f"Chunking failed: {e}")
            # Fallback to simple chunking
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000, chunk_overlap=200
            )
            return text_splitter.split_documents(docs)

    async def process_document(
        self,
        s3_url: str,
        filename: str,
        filetype: str,
        session_id: str,  # analogous to thread in langchain
        user_id: str,  # For seperation of conserns
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Main document processing pipeline with async/sync optimization.

        Args:
            s3_url: S3 URL of the document
            filename: Original filename
            filetype: File type/extension
            session_id: Session identifier
            user_id: User identifier
            metadata: Additional metadata

        Returns:
            Processing result dictionary

        Raises:
            InvalidURLError: If URL validation fails
            DocumentLoadError: If document loading fails
            SummaryGenerationError: If summary generation fails
        """
        # Fix file extension edge cases
        file_ext = (filetype or Path(filename).suffix or ".txt").lower()
        if not file_ext.startswith("."):
            file_ext = "." + file_ext

        logger.info(f"Processing {file_ext}: {filename}")

        try:
            # 1. ZERO DISK LOADING - Run blocking I/O in thread pool
            docs = await asyncio.to_thread(
                self._load_documents, s3_url, file_ext, filename
            )

            if not docs:
                raise DocumentLoadError(f"No documents loaded from {filename}")

            # Filter out empty documents
            valid_docs = []
            for doc in docs:
                if not doc.page_content.strip():
                    logger.warning(f"Empty document page from {filename}, skipping")
                    continue
                valid_docs.append(doc)

            if not valid_docs:
                raise ValueError(f"All documents from {filename} are empty")

            docs = valid_docs
            logger.info(f"Loaded {len(docs)} valid pages/sections")

            # 2. GENERATE SUMMARY FOR EVERY DOCUMENT (20k max)
            full_text = "\n\n".join([doc.page_content for doc in docs])
            summary_text = await self.generate_document_summary(
                full_text, filename, file_ext
            )

            # 3. SMART CHUNKING DECISION
            decision = self._should_chunk_document(full_text, file_ext)
            logger.info(f"Decision: {decision['message']}")

            # 4. PREPARE METADATA - Split into chunk metadata and session metadata
            is_code = file_ext.lower() in self.LANG_MAP

            # Lightweight chunk metadata - stored on every chunk (minimal storage overhead)
            chunk_metadata = {
                "session_id": session_id,
                "user_id": user_id,
                "filename": filename,
                "file_type": file_ext[1:],
                "is_code_file": is_code,
                "language": (
                    self.LANG_MAP.get(file_ext.lower()).value if is_code else None
                ),
            }

            # Heavy session-level metadata - stored once per document (not duplicated per chunk)
            session_metadata = {
                "session_id": session_id,
                "user_id": user_id,
                "filename": filename,
                "file_type": file_ext[1:],
                "s3_url": s3_url,
                "processed_at": datetime.now().isoformat(),
                "is_code_file": is_code,
                "token_count": decision["token_count"],
                "char_count": decision["char_count"],
                "chunking_strategy": decision["strategy"],
                "summary_text": summary_text,  # Heavy data - stored once
                "language": (
                    self.LANG_MAP.get(file_ext.lower()).value if is_code else None
                ),
                "total_chunks": 0,  # Will be updated after chunking
            }

            if metadata:
                chunk_metadata.update(metadata)
                session_metadata.update(metadata)

            # 5. PROCESS BASED ON CHUNKING DECISION
            for doc in docs:
                doc.metadata.update(chunk_metadata)

            if not decision["should_chunk"]:
                # SMALL: Embed whole
                for doc in docs:
                    doc.metadata.update(
                        {
                            "chunk_index": 0,
                            "total_chunks": 1,
                            "is_whole_document": True,
                        }
                    )
                chunks = docs
                logger.info(f"Embedding whole document")
            else:
                # Run blocking chunking in thread pool
                chunks = await asyncio.to_thread(
                    self._chunk_documents, docs, file_ext, decision["strategy"]
                )

            # Filter out any empty chunks that may have been created
            chunks = [c for c in chunks if c.page_content.strip()]

            if not chunks:
                raise ValueError(f"No valid content after splitting {filename}")

            logger.info(f"Final chunk count: {len(chunks)} valid chunks")

            # 6. SAFETY CHECK
            for i, chunk in enumerate(chunks):
                chunk_tokens = self._count_tokens(chunk.page_content)
                if chunk_tokens > self.EMBEDDING_MODEL_LIMIT:
                    logger.warning(
                        f"Truncating chunk {i}: {chunk_tokens}t > {self.EMBEDDING_MODEL_LIMIT}t"
                    )
                    encoded = self.tokenizer.encode(chunk.page_content)
                    safe_text = self.tokenizer.decode(
                        encoded[: self.EMBEDDING_MODEL_LIMIT - 100]
                    )
                    chunk.page_content = safe_text

            # 7. STORE IN VECTOR STORE
            logger.info(f"Storing {len(chunks)} chunks...")
            chunk_ids = self.vector_store.add_documents(chunks)
            logger.info(f"Stored {len(chunk_ids)} chunks")

            # Update session metadata with final chunk count
            session_metadata["total_chunks"] = len(chunks)

            # TODO: Store session_metadata in session storage (Redis/DB) using session_id as key
            # This avoids duplicating heavy data (summary_text, s3_url, etc.) across all chunks
            # Example: await session_store.set(session_id, filename, session_metadata)

            # 8. RETURN COMPLETE RESULT WITH SUMMARY
            return {
                "success": True,
                "filename": filename,
                "file_type": file_ext[1:],
                "is_code_file": is_code,
                "total_chunks": len(chunks),
                "chunk_ids": chunk_ids,
                "token_count": decision["token_count"],
                "char_count": decision["char_count"],
                "summary": summary_text,  # For session metadata storage
                "language": session_metadata.get("language"),
                "chunking_strategy": decision["strategy"],
                "is_whole_document": not decision["should_chunk"],
                "session_id": session_id,
                "user_id": user_id,
                "session_metadata": session_metadata,  # Complete metadata for session storage
                "message": f"Success: {filename}: {len(chunks)} chunks | Summary: {len(summary_text)} chars",
            }

        except InvalidURLError as e:
            # Security errors - re-raise immediately
            logger.error(f"URL validation failed: {e}", exc_info=True)
            raise

        except SummaryGenerationError as e:
            # Summary generation failed but we can still continue
            logger.error(f"Summary generation failed: {e}", exc_info=True)
            return {
                "success": False,
                "filename": filename,
                "file_type": file_ext[1:] if file_ext else "unknown",
                "error": f"Summary generation failed: {str(e)}",
                "error_type": "SummaryGenerationError",
                "session_id": session_id,
                "user_id": user_id,
                "message": f"Failed: {filename} - Summary generation error",
            }

        except DocumentLoadError as e:
            # Document loading failed
            logger.error(f"Document loading failed: {e}", exc_info=True)
            return {
                "success": False,
                "filename": filename,
                "file_type": file_ext[1:] if file_ext else "unknown",
                "error": str(e),
                "error_type": "DocumentLoadError",
                "session_id": session_id,
                "user_id": user_id,
                "message": f"Failed: {filename} - Document loading error",
            }

        except Exception as e:
            # Catch-all for unexpected errors
            logger.error(f"Processing failed: {e}", exc_info=True)
            return {
                "success": False,
                "filename": filename,
                "file_type": file_ext[1:] if file_ext else "unknown",
                "error": str(e),
                "error_type": type(e).__name__,
                "session_id": session_id,
                "user_id": user_id,
                "message": f"Failed: {filename}",
            }

    # ==================== SEARCH & RETRIEVAL METHODS ====================

    def search_documents(
        self,
        query: str,
        session_id: str,
        max_results: int = 5,
        file_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search with formatted results.
        Search documents in a session using vector similarity.

        Args:
            query: Search query text
            session_id: Session/thread ID to filter documents
            max_results: Maximum number of results to return (default: 5)
            file_type: Optional filter by file type (e.g., 'pdf', 'py')

        Returns:
            List of formatted result dictionaries containing:
                - content: Chunk text content
                - filename: Original filename
                - file_type: File extension
                - language: Programming language (if code)
                - chunk_index: Index of this chunk
                - total_chunks: Total chunks in document
                - is_code_file: Whether this is a code file
                - is_whole_document: Whether chunk is entire document

        Raises:
            Exception: If vector store search fails

        Example:
            results = processor.search_documents(
                query="How to implement authentication?",
                session_id="thread_123",
                max_results=5,
                file_type="py"
            )
            for result in results:
                print(f"{result['filename']}: {result['content'][:100]}...")
        """
        try:
            # Filter by session_id to get only docs from this thread
            pre_filter = {"session_id": {"$eq": session_id}}

            # Search with 2x buffer to account for file_type filtering
            results = self.vector_store.similarity_search(
                query=query, k=max_results * 2, pre_filter=pre_filter
            )

            # Optional: Filter by file type
            if file_type:
                results = [
                    doc for doc in results if doc.metadata.get("file_type") == file_type
                ]

            # Trim to max_results
            results = results[:max_results]

            # Format results for easy consumption
            formatted_results = []
            for doc in results:
                formatted_results.append(
                    {
                        "content": doc.page_content,
                        "filename": doc.metadata.get("filename"),
                        "file_type": doc.metadata.get("file_type"),
                        "language": doc.metadata.get("language"),
                        "chunk_index": doc.metadata.get("chunk_index"),
                        "total_chunks": doc.metadata.get("total_chunks"),
                        "is_code_file": doc.metadata.get("is_code_file", False),
                        "is_whole_document": doc.metadata.get(
                            "is_whole_document", False
                        ),
                    }
                )

            logger.info(
                f"Found {len(formatted_results)} relevant chunks for query: '{query[:50]}...'"
            )
            return formatted_results

        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            raise Exception(f"Document search failed: {str(e)}")

    async def retrieve_relevant_chunks(
        self, query: str, session_id: str, max_chunks: int = 5
    ) -> List[Document]:
        """
        Retrieve raw documents for RAG pipelines.
        Retrieve relevant document chunks as LangChain Documents for RAG integration.

        Args:
            query: Search query text
            session_id: Session/thread ID to filter documents
            max_chunks: Maximum number of chunks to return (default: 5)

        Returns:
            List of LangChain Document objects with full metadata.
            Returns empty list on error to avoid breaking RAG flow.

        Note:
            - Uses vector similarity search with session filtering
            - Returns raw Document objects (not formatted dicts)
            - Graceful error handling (returns [] instead of raising)
            - Ideal for feeding into RAG chains or LLM context

        Example:
            docs = await processor.retrieve_relevant_chunks(
                query="authentication implementation",
                session_id="thread_123",
                max_chunks=5
            )
            # Use in RAG chain
            context = "\n\n".join([doc.page_content for doc in docs])
        """
        try:
            # Filter by session_id
            pre_filter = {"session_id": {"$eq": session_id}}

            # Vector similarity search
            results = self.vector_store.similarity_search(
                query=query, k=max_chunks, pre_filter=pre_filter
            )

            logger.info(
                f"Retrieved {len(results)} relevant chunks for RAG | "
                f"Query: '{query[:50]}...' | Session: {session_id}"
            )
            return results

        except Exception as e:
            logger.error(f"Chunk retrieval failed for query '{query}': {e}")
            return []  # Return empty list instead of raising to avoid breaking RAG flow

    def get_document_summary(self, session_id: str, filename: str) -> Optional[str]:
        """
        Retrieve document summary from session metadata.

        Args:
            session_id: Session/thread ID
            filename: Document filename

        Returns:
            Summary text if found, None otherwise

        Note:
            Current implementation is a placeholder.
            In production, summaries should be fetched from session storage (Redis/DB)
            instead of chunk metadata for better performance and consistency.

        TODO:
            Replace with: session_store.get(session_id, filename)

        Example:
            summary = processor.get_document_summary(
                session_id="thread_123",
                filename="architecture.pdf"
            )
            if summary:
                print(f"Summary: {summary}")
        """
        try:
            pre_filter = {
                "session_id": {"$eq": session_id},
                "filename": {"$eq": filename},
            }

            # Get any chunk from this document
            # TODO: Replace with session_store.get(session_id, filename) for production
            results = self.vector_store.similarity_search(
                query=filename, k=1, pre_filter=pre_filter
            )

            if results:
                # Note: Summary should be in session storage, not chunk metadata
                # This is a fallback that may not work with optimized metadata
                logger.warning(
                    f"Retrieving summary from chunk metadata (use session storage in production)"
                )
                logger.info(f"Retrieved summary for {filename}")
                return f"Summary stored in session storage - fetch using session_id: {session_id}"
            else:
                logger.warning(f"No summary found for {filename}")
                return None

        except Exception as e:
            logger.error(f"Summary retrieval failed: {e}")
            return None

    def list_session_documents(self, session_id: str) -> List[Dict[str, Any]]:
        """
        List all documents in a session with metadata.
        Get metadata for all documents uploaded in a session (deduplicated by filename).

        Args:
            session_id: Session/thread ID to query

        Returns:
            List of document metadata dictionaries containing:
                - filename: Original filename
                - file_type: File extension
                - language: Programming language (if code)
                - is_code_file: Whether file is code
                - total_chunks: Number of chunks for this document
                - session_id: Session identifier

        Note:
            - Queries vector store with empty string (inefficient, see TODO)
            - Limited to 1000 documents per session
            - Automatically deduplicates by filename
            - Returns empty list on error

        TODO:
            Use metadata-only query if vector store supports it:
            vector_store.get_by_metadata(filter={"session_id": session_id})

        Example:
            docs = processor.list_session_documents("thread_123")
            for doc in docs:
                print(f"{doc['filename']}: {doc['total_chunks']} chunks")
                print(f"Type: {doc['file_type']}, Language: {doc['language']}")
        """
        try:
            pre_filter = {"session_id": {"$eq": session_id}}

            # Get all chunks from session
            results = self.vector_store.similarity_search(
                query="", k=1000, pre_filter=pre_filter  # Large number to get all docs
            )

            # Deduplicate by filename
            seen_files = {}
            for doc in results:
                filename = doc.metadata.get("filename")
                if filename and filename not in seen_files:
                    seen_files[filename] = {
                        "filename": filename,
                        "file_type": doc.metadata.get("file_type"),
                        "language": doc.metadata.get("language"),
                        "is_code_file": doc.metadata.get("is_code_file", False),
                        "total_chunks": doc.metadata.get("total_chunks"),
                        "session_id": session_id,
                    }

            documents = list(seen_files.values())
            logger.info(f"Found {len(documents)} documents in session {session_id}")
            return documents

        except Exception as e:
            logger.error(f"Failed to list session documents: {e}", exc_info=True)
            return []
