"""
Document Processor - Production Cloud-Based Parsing System

Document processing system that uses LlamaCloud API for efficient,
lightweight document parsing. Optimized for production with batch processing,
parallel operations, and comprehensive file format support.

FILE ORGANIZATION:
├─ SECTION 1: Imports & Configuration
├─ SECTION 2: Helper Functions & Utilities
├─ SECTION 3: DocumentProcessor Class
│  ├─ 3.1: Initialization & Core Utilities
│  ├─ 3.2: File Downloading & Text Loading
│  ├─ 3.3: Document Parsing (Single & Batch)
│  ├─ 3.4: Document Analysis & Summarization
│  ├─ 3.5: Chunking & Validation
│  ├─ 3.6: Document Processing Pipeline
│  └─ 3.7: Search & Retrieval Methods
└─ LEGACY: See document_processor_legacy.py for archived methods

USAGE:
    # Single document
    processor = DocumentProcessor()
    result = await processor.process_documents(
        docs={"filename": "doc.pdf", "public_url": "...", "filetype": ".pdf"},
        session_id="thread_123",
        user_id="user_456"
    )

    # Multiple documents (automatic batch optimization)
    results = await processor.process_documents(
        docs=[
            {"filename": "doc1.pdf", "public_url": "...", "filetype": ".pdf"},
            {"filename": "doc2.py", "public_url": "...", "filetype": ".py"}
        ],
        session_id="thread_123",
        user_id="user_456"
    )

    # Search documents
    search_results = await processor.search_documents(
        query="machine learning",
        session_id="thread_123",
        limit=10
    )
"""

# ============================================================================
# SECTION 1: IMPORTS & CONFIGURATION
# ============================================================================

import os
import re
import logging
import asyncio
import tempfile
import aiohttp
import tiktoken
from io import BytesIO
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional, Union, Literal
from pathlib import Path
from datetime import datetime

from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language
from langchain_core.documents import Document
from langchain_community.document_loaders import TextLoader
from pydantic import BaseModel, Field, field_validator

from vector_store import get_vector_store
from services.llama_parse_service import LlamaParseService
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ============================================================================
# SECTION 2: DOCUMENT INFO MODEL - NestJS Backend Interface
# ============================================================================
#
# DocInfo defines the expected structure from NestJS backend for document processing.
# This ensures type safety and consistency across the service.
#
# Expected from NestJS for each document:
# 1. filename: Document name (e.g., "project_documentation.pdf")
# 2. filetype: File extension (e.g., ".pdf", "pdf", ".py")
# 3. public_url: Publicly accessible URL (S3, DigitalOcean Spaces, etc.)
# 4. metadata: Optional flexible dictionary (can contain pages, size, etc.)
#
# Example:
#     {
#         "filename": "project_documentation.pdf",
#         "filetype": ".pdf",
#         "public_url": "https://bucket.s3.amazonaws.com/docs/project_documentation.pdf",
#         "metadata": {
#             "pages": 25,
#             "file_size": 1024000,
#             "uploaded_at": "2025-01-08T10:30:00Z"
#         }
#     }
# ============================================================================


class DocInfo(BaseModel):
    """
    Document information model for NestJS backend input.
    This model defines the structure expected when processing documents.
    Each document should have this structure.
    Fields:
        filename: Original filename (required)
        filetype: File extension with or without leading dot (required)
        public_url: Publicly accessible URL to the document (required)
        metadata: Optional flexible dictionary for any additional info
    """

    filename: str = Field(
        ...,
        description="Original filename of the document",
        min_length=1,
        examples=["project_documentation.pdf", "script.py", "report.docx"],
    )

    filetype: str = Field(
        ...,
        alias="file_type",  # Also accept file_type for backwards compatibility
        description="File extension (e.g., '.pdf', 'pdf', '.py')",
        min_length=1,
        examples=[".pdf", "pdf", ".docx", ".py", ".js"],
    )

    public_url: str = Field(
        ...,
        alias="s3_url",  # Also accept s3_url for backwards compatibility
        description="Publicly accessible URL (S3, DigitalOcean Spaces, etc.)",
        examples=[
            "https://bucket.s3.amazonaws.com/path/to/file.pdf",
            "https://name.nyc3.digitaloceanspaces.com/path/to/file.pdf",
        ],
    )

    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional flexible metadata (pages, file_size, uploaded_at, etc.)",
    )

    @field_validator("filetype")
    @classmethod
    def validate_filetype(cls, v: str) -> str:
        """Normalize filetype to always have leading dot (e.g., 'pdf' -> '.pdf')."""
        if not v:
            raise ValueError("filetype cannot be empty")
        normalized = v.lower().strip()
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        return normalized

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        """Ensure filename is not empty."""
        if not v or not v.strip():
            raise ValueError("filename cannot be empty")
        return v.strip()

    class Config:
        populate_by_name = True  # Allow both filetype/file_type, public_url/s3_url
        json_schema_extra = {
            "example": {
                "filename": "project_documentation.pdf",
                "filetype": ".pdf",
                "public_url": "https://bucket.s3.amazonaws.com/docs/project_documentation.pdf",
                "metadata": {
                    "pages": 25,
                    "file_size": 1024000,
                    "uploaded_at": "2025-01-08T10:30:00Z",
                },
            }
        }


# ============================================================================
# SECTION 3: CUSTOM EXCEPTIONS
# ============================================================================


class DocumentProcessingError(Exception):
    """Base exception for document processing errors"""

    pass


class SummaryGenerationError(DocumentProcessingError):
    """Exception raised when summary generation fails"""

    pass


class DocumentLoadError(DocumentProcessingError):
    """Exception raised when document loading fails"""

    pass


# ============================================================================
# SECTION 3: HELPER FUNCTIONS
# ============================================================================


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


# ============================================================================
# SECTION 4: DOCUMENT PROCESSOR CLASS
# ============================================================================


class DocumentProcessor:
    # Token thresholds
    SMALL_SUMMARY_THRESHOLD = 500  # Documents smaller than this skip LLM summarization
    EMBED_WHOLE_THRESHOLD = 1000  # Below this: embed whole, don't chunk if small
    EMBEDDING_MODEL_LIMIT = 8191  # Safety check: text-embedding-3-small/large limit
    MAX_SUMMARY_TOKENS = 20000  # Summary truncation limit

    # Rate limiting
    MAX_CONCURRENT_SUMMARIES = 20  # Maximum concurrent LLM calls
    SUMMARY_TIMEOUT = 120  # Timeout for summary generation (seconds)

    LANG_MAP = {
        # Documents
        ".md": Language.MARKDOWN,
        ".markdown": Language.MARKDOWN,
        ".html": Language.HTML,
        ".htm": Language.HTML,
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
        # JVM Languages
        ".java": Language.JAVA,
        # Systems
        ".go": Language.GO,
        ".rs": Language.RUST,
        ".rb": Language.RUBY,
    }

    # File configuration dictionary defining supported file formats and their processing settings.
    # This dictionary serves as the single source of truth for:
    # 1. Which file formats are supported by the document processor
    # 2. Which loader to use for each format (llamaparse or text)
    # 3. Chunking configuration (chunk_size and chunk_overlap)
    #
    # Loader Types:
    # - "llamaparse": Use Llama Cloud API for parsing (PDFs, Office docs, etc.)
    # - "text": Use TextLoader for code files and plain text formats
    #
    # Only widely used formats for full-stack code generation platforms are included.
    # Formats not in this dictionary will default to text loader with standard chunking.
    FILE_CONFIGS = {
        # ==================== DOCUMENT FORMATS (Use LlamaParse) ====================
        # PDF Documents
        ".pdf": {"loader": "llamaparse", "chunk_size": 1000, "chunk_overlap": 200},
        # Microsoft Word Documents (Most Common)
        ".docx": {"loader": "llamaparse", "chunk_size": 1000, "chunk_overlap": 200},
        ".doc": {"loader": "llamaparse", "chunk_size": 1000, "chunk_overlap": 200},
        # Microsoft Excel Spreadsheets (Most Common)
        ".xlsx": {"loader": "llamaparse", "chunk_size": 1000, "chunk_overlap": 200},
        ".xls": {"loader": "llamaparse", "chunk_size": 1000, "chunk_overlap": 200},
        ".csv": {"loader": "llamaparse", "chunk_size": 1000, "chunk_overlap": 200},
        # Microsoft PowerPoint Presentations (Most Common)
        ".pptx": {"loader": "llamaparse", "chunk_size": 1000, "chunk_overlap": 200},
        ".ppt": {"loader": "llamaparse", "chunk_size": 1000, "chunk_overlap": 200},
        # Text and Markup Documents
        ".txt": {"loader": "llamaparse", "chunk_size": 1000, "chunk_overlap": 200},
        ".html": {"loader": "llamaparse", "chunk_size": 1200, "chunk_overlap": 150},
        ".htm": {"loader": "llamaparse", "chunk_size": 1200, "chunk_overlap": 150},
        ".xml": {"loader": "llamaparse", "chunk_size": 1000, "chunk_overlap": 200},
        ".md": {
            "loader": "text",
            "chunk_size": 1000,
            "chunk_overlap": 200,
        },  # Markdown - use text loader
        ".markdown": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        # ==================== CODE FILES (Use Text Loader) ====================
        # Python
        ".py": {"loader": "text", "chunk_size": 1500, "chunk_overlap": 200},
        # JavaScript/TypeScript
        ".js": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".jsx": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".ts": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".tsx": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        # C Family
        ".c": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        ".cpp": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        # JVM Languages
        ".java": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        # Systems
        ".go": {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
    }

    # Type alias for supported file extensions (derived from FILE_CONFIGS)
    # This ensures type safety when specifying file extensions
    SupportedFileExtension = Literal[
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".csv",
        ".pptx",
        ".ppt",
        ".txt",
        ".html",
        ".htm",
        ".xml",
        ".md",
        ".markdown",
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".c",
        ".cpp",
        ".java",
        ".go",
    ]

    def __init__(self):
        """
        Initialize DocumentProcessor with vector store, tokenizer, summarizer, and Llama Parse service.
        """
        self.vector_store = get_vector_store("document")
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        self.summarizer = get_summarizer_model()
        self.summary_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_SUMMARIES)
        self.llama_parse_service = LlamaParseService()
        logger.info("DocumentProcessor initialized")

    # ========================================================================
    # 4.1: FORMAT UTILITIES (Commented - See UTILITY_METHODS_EXPLANATION.md)
    # ========================================================================
    # TODO: Utility methods for format validation and API endpoints
    # USE CASE: Replace hardcoded format lists in asset_upload_routes.py (line 195-224)
    #          to prevent format list duplication and keep route validation in sync
    # FUTURE:  Add GET /api/assets/supported-formats endpoint for frontend integration
    # See: UTILITY_METHODS_EXPLANATION.md for full details

    # @classmethod
    # def get_supported_formats(cls) -> Dict[str, List[str]]:
    #     """
    #     Get list of supported file formats organized by loader type.
    #
    #     Returns:
    #         Dictionary with keys:
    #             - "llamaparse": List of file extensions using Llama Cloud parser
    #             - "text": List of file extensions using TextLoader
    #             - "all": List of all supported file extensions
    #     """
    #     llamaparse_formats = []
    #     text_formats = []
    #
    #     for ext, config in cls.FILE_CONFIGS.items():
    #         loader = config.get("loader", "text")
    #         if loader == "llamaparse":
    #             llamaparse_formats.append(ext)
    #         else:
    #             text_formats.append(ext)
    #
    #     return {
    #         "llamaparse": sorted(llamaparse_formats),
    #         "text": sorted(text_formats),
    #         "all": sorted(list(cls.FILE_CONFIGS.keys())),
    #     }
    #
    # @classmethod
    # def is_format_supported(cls, file_ext: str) -> bool:
    #     """
    #     Check if a file format is supported by the document processor.
    #
    #     Args:
    #         file_ext: File extension (with or without leading dot, e.g., '.pdf' or 'pdf')
    #
    #     Returns:
    #         True if format is supported, False otherwise
    #     """
    #     if not file_ext.startswith("."):
    #         file_ext = f".{file_ext}"
    #     return file_ext.lower() in cls.FILE_CONFIGS

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

    # ========================================================================
    # 4.2: FILE DOWNLOADING & TEXT LOADING
    # ========================================================================

    async def _download_remote_file(
        self, url: str, suffix: Union[SupportedFileExtension, str] = ""
    ) -> str:
        """
        Download a remote file (e.g., S3/Spaces presigned URL) to a temp file asynchronously.

        Args:
            url: Remote URL to download from
            suffix: File extension suffix for temp file (must be from FILE_CONFIGS, e.g., '.pdf', '.docx')
                   Use empty string "" for unknown extensions (fallback).

        Returns:
            Path to temporary file

        Raises:
            aiohttp.ClientError: If download fails
            OSError: If temp file creation fails

        Note:
            - Caller is responsible for cleaning up the temp file
            - Suffix should be one of the supported extensions from FILE_CONFIGS
            - Type hint ensures only valid extensions are used at compile time
        """
        # Validate suffix is from FILE_CONFIGS (runtime check)
        if suffix and suffix not in self.FILE_CONFIGS:
            logger.warning(
                f"Suffix '{suffix}' not in FILE_CONFIGS. Supported: {list(self.FILE_CONFIGS.keys())}"
            )

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=300)
            ) as resp:
                resp.raise_for_status()
                data = await resp.read()

        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            logger.debug(f"Downloaded remote file to temp: {tmp_path}")
            return tmp_path
        except Exception as e:
            # Clean up on error
            try:
                os.close(fd)
                os.remove(tmp_path)
            except:
                pass
            raise DocumentLoadError(f"Failed to save downloaded file: {e}")

        #     Args:

    def _load_as_text(self, file_path: str) -> str:
        """
        Load file as plain text using LangChain's TextLoader for unsupported formats.

        This method handles files that LlamaParse doesn't support (code files, etc.).

        Args:
            file_path: Path to file

        Returns:
            File content as plain text string

        Raises:
            Exception: If file cannot be loaded
        """
        try:
            # Use LangChain's TextLoader which handles encoding detection
            loader = TextLoader(file_path, encoding="utf-8", autodetect_encoding=True)
            documents = loader.load()
            # Join all document pages with double newline
            return "\n\n".join(doc.page_content for doc in documents)
        except Exception as e:
            # Fallback: try reading with BytesIO
            logger.warning(f"TextLoader failed for {file_path}, using fallback: {e}")
            try:
                with open(file_path, "rb") as f:
                    text = BytesIO(f.read()).read().decode("utf-8", errors="ignore")
                    return text
            except Exception as e2:
                # Last resort: try latin-1 which accepts all bytes
                logger.warning(f"UTF-8 failed for {file_path}, trying latin-1: {e2}")
                with open(file_path, "rb") as f:
                    text = BytesIO(f.read()).read().decode("latin-1", errors="ignore")
                    return text

    # ========================================================================
    # 4.3: DOCUMENT PARSING - Single & Batch ( NEW OPTIMIZATION)
    # ========================================================================
    #
    # Methods:
    #   - _parse_document(): Single document parsing (used for 1 doc optimization)
    #   - _parse_documents_batch():  NEW - Batch parsing with smart grouping
    #   - _batch_parse_llamaparse():  NEW - LlamaParse batch processor
    #   - _batch_parse_text():  NEW - Text batch processor
    #
    # Performance: 4x faster, 80% cost reduction for multiple documents
    # See: BATCH_PROCESSING_USAGE.md for details
    # ========================================================================

    async def _parse_document(
        self, public_url: str, file_ext: str, filename: str
    ) -> str:
        """
        Parse SINGLE document from remote URL using appropriate loader based on FILE_CONFIGS.

        This method downloads the document to a temporary file, parses it using the configured
        loader (LlamaParse or TextLoader), then cleans up the temp file.

        NOTE: For multiple documents, use _parse_documents_batch() instead for better performance.
              Batch processing groups documents by loader type and reduces API calls.

        Loader Selection:
        - "llamaparse": Uses Llama Cloud API for PDFs, Office docs, HTML, etc.
        - "text": Uses TextLoader for code files (.py, .js, .go, etc.) and plain text

        Args:
            public_url: Remote URL to parse (S3, DigitalOcean Spaces, or any accessible URL)
            file_ext: File extension with or without leading dot (e.g., '.pdf', 'pdf', '.docx')
            filename: Original filename (for logging and error messages)

        Returns:
            Parsed text content as string (markdown format for LlamaParse, plain text for TextLoader)

        Raises:
            DocumentLoadError: If download, parsing, or file access fails

        Example:
            parsed_text = await processor._parse_document(
                public_url="https://bucket.s3.amazonaws.com/doc.pdf",
                file_ext=".pdf",
                filename="document.pdf"
            )

        See Also:
            _parse_documents_batch(): Optimized batch parsing for multiple documents
        """
        # Normalize file extension to always have leading dot
        if file_ext and not file_ext.startswith("."):
            file_ext = f".{file_ext}"
        file_ext = file_ext.lower() if file_ext else ".txt"

        # Get file configuration to determine loader type
        config = self.FILE_CONFIGS.get(
            file_ext,
            {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
        )
        loader_type = config.get("loader", "text")

        tmp_path = None
        try:
            # Download to temp file
            logger.info(
                f"Downloading remote file: {filename} from {public_url[:50]}..."
            )
            tmp_path = await self._download_remote_file(public_url, suffix=file_ext)

            # Use appropriate loader based on configuration
            if loader_type == "llamaparse":
                # Check if format is supported by LlamaParse
                if not self.llama_parse_service.is_supported_format(tmp_path):
                    logger.warning(
                        f"Format {file_ext} configured for llamaparse but not supported by LlamaParse, "
                        f"falling back to text loader: {filename}"
                    )
                    parsed_text = await asyncio.to_thread(self._load_as_text, tmp_path)
                else:
                    # Parse using Llama Cloud service
                    logger.info(f"Parsing with Llama Cloud API: {filename}")
                    parsed_text = await self.llama_parse_service.parse_single_file(
                        tmp_path
                    )

                # Convert to string if needed
                if not isinstance(parsed_text, str):
                    parsed_text = str(parsed_text)

            elif loader_type == "text":
                # Use TextLoader for code files and plain text
                logger.info(f"Loading as text: {filename}")
                parsed_text = await asyncio.to_thread(self._load_as_text, tmp_path)

            else:
                # Unknown loader type, default to text
                logger.warning(
                    f"Unknown loader type '{loader_type}' for {file_ext}, "
                    f"defaulting to text loader: {filename}"
                )
                parsed_text = await asyncio.to_thread(self._load_as_text, tmp_path)

            # Validate parsed content
            if not parsed_text or not parsed_text.strip():
                raise DocumentLoadError(
                    f"Parsed content is empty for {filename}. "
                    f"The document may be corrupted or unsupported."
                )

            logger.info(
                f"Successfully parsed {filename}: {len(parsed_text)} characters "
                f"(loader: {loader_type}, extension: {file_ext})"
            )
            return parsed_text

        except DocumentLoadError:
            # Re-raise document load errors as-is
            raise
        except Exception as e:
            error_msg = (
                f"Failed to parse document {filename} ({file_ext}): {str(e)}. "
                f"URL: {public_url[:100]}"
            )
            logger.error(error_msg, exc_info=True)
            raise DocumentLoadError(error_msg)
        finally:
            # Always clean up temp file, even on error
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    logger.debug(f"Cleaned up temp file: {tmp_path}")
                except OSError as e:
                    logger.warning(
                        f"Failed to clean up temp file {tmp_path}: {e}. "
                        f"File may need manual cleanup."
                    )

    async def _parse_documents_batch(
        self, docs_info: Union[List[DocInfo], List[Dict[str, Any]]]
    ) -> List[Dict[str, str]]:
        """
        Parse multiple documents in batch, grouped by loader type for optimal performance.

        This method intelligently groups documents by their loader type (llamaparse vs text)
        and processes each group efficiently:
        - LlamaParse docs: Single batch API call (cost-effective, 80% reduction)
        - Text docs: Parallel text loading (all files processed simultaneously)

        The method maintains the original order of documents in the results, even if
        processing happens in parallel.

        Args:
            docs_info: List of DocInfo models or dicts with keys: public_url, file_ext, filename
                Example with DocInfo:
                    [
                        DocInfo(filename="doc1.pdf", filetype=".pdf", public_url="https://..."),
                        DocInfo(filename="script.py", filetype=".py", public_url="https://...")
                    ]
                Example with dicts (backwards compatible):
                    [
                        {"public_url": "https://...", "file_ext": ".pdf", "filename": "doc1.pdf"},
                        {"public_url": "https://...", "file_ext": ".py", "filename": "script.py"}
                    ]

        Returns:
            List of dicts with keys: filename, parsed_text, file_ext (in original order)
            Each result dict may also contain an "error" key if parsing failed.
                Example: [
                    {"filename": "doc1.pdf", "parsed_text": "...", "file_ext": ".pdf"},
                    {"filename": "script.py", "parsed_text": "...", "file_ext": ".py", "error": "..."}
                ]

        Performance:
            - 5 PDFs: 1 API call instead of 5 (4x faster, 80% cost reduction)
            - Mixed types: Automatically optimizes by grouping
            - Parallel processing: Both groups processed simultaneously

        Raises:
            ValueError: If docs_info is empty
        """
        if not docs_info:
            raise ValueError("docs_info cannot be empty")

        # Convert DocInfo models to dicts for processing
        normalized_docs = []
        for doc in docs_info:
            if isinstance(doc, DocInfo):
                normalized_docs.append(
                    {
                        "filename": doc.filename,
                        "file_ext": doc.filetype,  # DocInfo uses filetype (already normalized)
                        "public_url": str(doc.public_url),
                        "metadata": doc.metadata or {},
                    }
                )
            else:
                # Already a dict, use as-is
                normalized_docs.append(doc)

        # Group documents by loader type
        llamaparse_docs = []
        text_docs = []

        for doc_info in normalized_docs:
            # Normalize file extension
            file_ext = doc_info.get("file_ext", "")
            if file_ext and not file_ext.startswith("."):
                file_ext = f".{file_ext}"
            file_ext = file_ext.lower() if file_ext else ".txt"

            # Get loader type from FILE_CONFIGS
            config = self.FILE_CONFIGS.get(
                file_ext,
                {"loader": "text", "chunk_size": 1000, "chunk_overlap": 200},
            )
            loader_type = config.get("loader", "text")

            # Add normalized file_ext and loader_type to doc info
            doc_with_loader = {
                **doc_info,
                "file_ext": file_ext,
                "loader_type": loader_type,
            }

            if loader_type == "llamaparse":
                llamaparse_docs.append(doc_with_loader)
            else:
                text_docs.append(doc_with_loader)

        logger.info(
            f"Batch parsing {len(normalized_docs)} documents: "
            f"{len(llamaparse_docs)} llamaparse, {len(text_docs)} text"
        )

        # Process both groups in parallel
        results = {}
        tasks = []

        if llamaparse_docs:
            tasks.append(self._batch_parse_llamaparse(llamaparse_docs))
        if text_docs:
            tasks.append(self._batch_parse_text(text_docs))

        if not tasks:
            logger.warning("No documents to process after grouping")
            return []

        # Execute batch processing tasks in parallel
        group_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results from both groups
        for group_result in group_results:
            if isinstance(group_result, Exception):
                logger.error(
                    f"Batch parsing group failed: {group_result}", exc_info=True
                )
                continue

            # Merge into results dict by filename
            for item in group_result:
                filename = item.get("filename")
                if filename:
                    results[filename] = item

        # Return results in original order
        ordered_results = []
        for doc_info in normalized_docs:
            filename = doc_info.get("filename")
            if not filename:
                logger.warning("Document info missing filename, skipping")
                continue

            if filename in results:
                ordered_results.append(results[filename])
            else:
                # Failed to parse - add error placeholder
                logger.error(f"No parse result for {filename}")
                ordered_results.append(
                    {
                        "filename": filename,
                        "parsed_text": "",
                        "file_ext": doc_info.get("file_ext", ""),
                        "error": "Parsing failed - no result returned",
                    }
                )

        success_count = sum(
            1 for r in ordered_results if r.get("parsed_text") and not r.get("error")
        )
        logger.info(
            f"Batch parsing complete: {success_count}/{len(ordered_results)} succeeded"
        )

        return ordered_results

    async def _batch_parse_llamaparse(
        self, docs_info: Union[List[DocInfo], List[Dict[str, Any]]]
    ) -> List[Dict[str, str]]:
        """
        Batch parse multiple documents using LlamaParse (single API call for efficiency).

        This method processes all LlamaParse-compatible documents in a single batch API call,
        significantly reducing API costs and processing time compared to individual calls.

        Process:
        1. Download all files to temp (parallel download)
        2. Parse all files in single batch API call (cost-effective)
        3. Validate parsed content
        4. Cleanup temp files (always, even on error)

        Args:
            docs_info: List of DocInfo models or dicts with keys: public_url, file_ext, filename, loader_type
                All documents in this list should have loader_type="llamaparse"
                Can accept DocInfo models or dicts (backwards compatible)

        Returns:
            List of dicts with keys: filename, parsed_text, file_ext
            Failed documents include an "error" key with error message

        Performance:
            - 5 PDFs: 1 API call instead of 5 (80% cost reduction)
            - Processing time: ~5-10s for batch vs ~25s for sequential

        Raises:
            ValueError: If docs_info is empty
        """
        if not docs_info:
            logger.warning("Empty docs_info list provided to _batch_parse_llamaparse")
            return []

        # Convert DocInfo models to dicts for processing
        normalized_docs = []
        for doc in docs_info:
            if isinstance(doc, DocInfo):
                normalized_docs.append(
                    {
                        "filename": doc.filename,
                        "file_ext": doc.filetype,
                        "public_url": str(doc.public_url),
                        "loader_type": "llamaparse",
                    }
                )
            else:
                normalized_docs.append(doc)

        # Step 1: Download all files to temp (parallel)
        logger.info(
            f"Step 1/3: Downloading {len(normalized_docs)} files for LlamaParse batch processing"
        )
        download_tasks = [
            self._download_remote_file(doc["public_url"], suffix=doc["file_ext"])
            for doc in normalized_docs
        ]
        tmp_paths = await asyncio.gather(*download_tasks, return_exceptions=True)

        # Step 2: Check for download failures and build valid list
        valid_indices = []
        valid_tmp_paths = []
        failed_downloads = []

        for i, tmp_path in enumerate(tmp_paths):
            if isinstance(tmp_path, Exception):
                filename = normalized_docs[i].get("filename", "unknown")
                logger.error(
                    f"Failed to download {filename}: {tmp_path}",
                    exc_info=True,
                )
                failed_downloads.append(i)
            else:
                valid_indices.append(i)
                valid_tmp_paths.append(tmp_path)

        # If all downloads failed, return error results
        if not valid_tmp_paths:
            logger.error("All downloads failed for LlamaParse batch")
            return [
                {
                    "filename": doc["filename"],
                    "parsed_text": "",
                    "file_ext": doc["file_ext"],
                    "error": f"Download failed: {str(tmp_paths[i])}",
                }
                for i, doc in enumerate(normalized_docs)
            ]

        # Log download summary
        if failed_downloads:
            logger.warning(
                f"Downloaded {len(valid_tmp_paths)}/{len(normalized_docs)} files successfully. "
                f"{len(failed_downloads)} downloads failed."
            )

        # Step 3: Batch parse with single API call
        try:
            logger.info(
                f"Step 2/3: Batch parsing {len(valid_tmp_paths)} documents with LlamaParse "
                f"(1 API call for {len(valid_tmp_paths)} documents)"
            )
            parsed_texts = await self.llama_parse_service.parse_multiple_files(
                valid_tmp_paths
            )

            # Step 4: Build results for successfully parsed documents
            results = []
            for i, valid_idx in enumerate(valid_indices):
                doc_info = normalized_docs[valid_idx]
                filename = doc_info.get("filename", "unknown")

                # Get parsed text (handle index mismatch)
                if i < len(parsed_texts):
                    parsed_text = parsed_texts[i]
                else:
                    logger.warning(
                        f"Index mismatch: parsed_texts has {len(parsed_texts)} items, "
                        f"but expected at least {i+1} for {filename}"
                    )
                    parsed_text = ""

                # Convert to string if needed
                if not isinstance(parsed_text, str):
                    parsed_text = str(parsed_text)

                # Validate parsed content
                if not parsed_text or not parsed_text.strip():
                    logger.warning(
                        f"Parsed content is empty for {filename}. "
                        f"Document may be corrupted or unsupported."
                    )
                    results.append(
                        {
                            "filename": filename,
                            "parsed_text": "",
                            "file_ext": doc_info.get("file_ext", ""),
                            "error": "Parsed content is empty",
                        }
                    )
                else:
                    results.append(
                        {
                            "filename": filename,
                            "parsed_text": parsed_text,
                            "file_ext": doc_info.get("file_ext", ""),
                        }
                    )

            # Add error results for failed downloads
            for i in failed_downloads:
                doc_info = normalized_docs[i]
                results.append(
                    {
                        "filename": doc_info.get("filename", "unknown"),
                        "parsed_text": "",
                        "file_ext": doc_info.get("file_ext", ""),
                        "error": f"Download failed: {str(tmp_paths[i])}",
                    }
                )

            success_count = sum(
                1 for r in results if r.get("parsed_text") and not r.get("error")
            )
            logger.info(
                f"Step 3/3: Successfully batch parsed {success_count}/{len(normalized_docs)} "
                f"documents with LlamaParse"
            )

            return results

        except Exception as e:
            logger.error(
                f"LlamaParse batch processing failed: {e}",
                exc_info=True,
            )
            # Return error results for all documents
            error_results = []
            for i, doc_info in enumerate(normalized_docs):
                if i in valid_indices:
                    # Was downloaded but parsing failed
                    error_results.append(
                        {
                            "filename": doc_info.get("filename", "unknown"),
                            "parsed_text": "",
                            "file_ext": doc_info.get("file_ext", ""),
                            "error": f"LlamaParse API error: {str(e)}",
                        }
                    )
                else:
                    # Download already failed
                    error_results.append(
                        {
                            "filename": doc_info.get("filename", "unknown"),
                            "parsed_text": "",
                            "file_ext": doc_info.get("file_ext", ""),
                            "error": f"Download failed: {str(tmp_paths[i])}",
                        }
                    )
            return error_results

        finally:
            # Always cleanup temp files, even on error
            logger.debug(f"Cleaning up {len(valid_tmp_paths)} temp files")
            cleanup_errors = 0
            for tmp_path in valid_tmp_paths:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError as e:
                        cleanup_errors += 1
                        logger.warning(
                            f"Failed to cleanup temp file {tmp_path}: {e}. "
                            f"File may need manual cleanup."
                        )

            if cleanup_errors > 0:
                logger.warning(
                    f"Failed to cleanup {cleanup_errors}/{len(valid_tmp_paths)} temp files"
                )

    async def _batch_parse_text(
        self, docs_info: Union[List[DocInfo], List[Dict[str, Any]]]
    ) -> List[Dict[str, str]]:
        """
        Parse multiple text/code documents in parallel using TextLoader.

        This method processes all text/code files simultaneously using parallel async tasks.
        Each file is downloaded, loaded as text, and cleaned up independently.

        Process:
        1. Download each file to temp (parallel)
        2. Load text content using TextLoader (parallel)
        3. Validate parsed content
        4. Cleanup temp files (per-file, always)

        Args:
            docs_info: List of DocInfo models or dicts with keys: public_url, file_ext, filename, loader_type
                All documents in this list should have loader_type="text"
                Can accept DocInfo models or dicts (backwards compatible)

        Returns:
            List of dicts with keys: filename, parsed_text, file_ext
            Failed documents include an "error" key with error message

        Performance:
            - All files processed in parallel (no sequential bottlenecks)
            - 10 code files: ~2-3s total (vs ~10s sequential)

        Raises:
            ValueError: If docs_info is empty
        """
        if not docs_info:
            logger.warning("Empty docs_info list provided to _batch_parse_text")
            return []

        # Convert DocInfo models to dicts for processing
        normalized_docs = []
        for doc in docs_info:
            if isinstance(doc, DocInfo):
                normalized_docs.append(
                    {
                        "filename": doc.filename,
                        "file_ext": doc.filetype,
                        "public_url": str(doc.public_url),
                        "loader_type": "text",
                    }
                )
            else:
                normalized_docs.append(doc)

        async def parse_one_text(doc_info: Dict[str, str]) -> Dict[str, str]:
            """
            Parse a single text/code document.

            Handles download, text loading, validation, and cleanup for one file.
            """
            filename = doc_info.get("filename", "unknown")
            file_ext = doc_info.get("file_ext", "")
            public_url = doc_info.get("public_url", "")
            tmp_path = None

            try:
                # Download to temp file
                tmp_path = await self._download_remote_file(public_url, suffix=file_ext)

                # Load text content using TextLoader
                text = await asyncio.to_thread(self._load_as_text, tmp_path)

                # Validate parsed content
                if not text or not text.strip():
                    logger.warning(
                        f"Parsed content is empty for {filename}. "
                        f"File may be empty or corrupted."
                    )
                    return {
                        "filename": filename,
                        "parsed_text": "",
                        "file_ext": file_ext,
                        "error": "Parsed content is empty",
                    }

                return {
                    "filename": filename,
                    "parsed_text": text,
                    "file_ext": file_ext,
                }

            except Exception as e:
                logger.error(
                    f"Failed to parse text file {filename}: {e}",
                    exc_info=True,
                )
                return {
                    "filename": filename,
                    "parsed_text": "",
                    "file_ext": file_ext,
                    "error": str(e),
                }

            finally:
                # Always cleanup temp file, even on error
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError as e:
                        logger.warning(
                            f"Failed to cleanup temp file {tmp_path}: {e}. "
                            f"File may need manual cleanup."
                        )

        # Parse all text docs in parallel
        logger.info(
            f"Parallel parsing {len(normalized_docs)} text/code documents "
            f"(all files processed simultaneously)"
        )

        results = await asyncio.gather(
            *[parse_one_text(doc) for doc in normalized_docs], return_exceptions=True
        )

        # Process results and handle exceptions
        valid_results = []
        exception_count = 0

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                exception_count += 1
                filename = normalized_docs[i].get("filename", "unknown")
                logger.error(
                    f"Text parsing task failed for {filename}: {result}",
                    exc_info=True,
                )
                # Add error result
                valid_results.append(
                    {
                        "filename": filename,
                        "parsed_text": "",
                        "file_ext": normalized_docs[i].get("file_ext", ""),
                        "error": f"Task exception: {str(result)}",
                    }
                )
            else:
                valid_results.append(result)

        success_count = sum(
            1 for r in valid_results if r.get("parsed_text") and not r.get("error")
        )

        if exception_count > 0:
            logger.warning(
                f"Text parsing complete: {success_count}/{len(normalized_docs)} succeeded, "
                f"{exception_count} tasks failed with exceptions"
            )
        else:
            logger.info(
                f"Successfully parsed {success_count}/{len(normalized_docs)} text/code documents"
            )

        return valid_results

    # ========================================================================
    # 4.4: DOCUMENT ANALYSIS & SUMMARIZATION
    # ========================================================================

    def _should_chunk_document(self, text: str, file_ext: str) -> Dict[str, Any]:
        """
        Determine if document should be chunked based on size and content analysis.

        This method analyzes the document size (token count and character count) to decide
        whether chunking is necessary. Small documents are embedded whole for efficiency,
        while larger documents are chunked to fit within embedding model limits.

        Decision Logic:
        - Small files (< EMBED_WHOLE_THRESHOLD tokens): Embedded whole (no chunking)
        - Medium/Large files (>= EMBED_WHOLE_THRESHOLD tokens): Chunked with standard strategy

        Args:
            text: Full document text content (required, non-empty)
            file_ext: File extension with leading dot (e.g., '.py', '.pdf', '.docx')

        Returns:
            Dictionary containing decision metadata:
                - should_chunk (bool): Whether to chunk the document
                - reason (str): Decision reason code ('small_file' or 'large_or_medium_file')
                - token_count (int): Total tokens in document (using tiktoken)
                - char_count (int): Total characters in document
                - strategy (str): Chunking strategy ('embed_whole' or 'standard_chunking')
                - message (str): Human-readable decision message for logging

        Raises:
            ValueError: If text is empty or None

        Example:
            decision = processor._should_chunk_document(
                text="Long document content...",
                file_ext=".pdf"
            )
            # Returns: {
            #     "should_chunk": True,
            #     "reason": "large_or_medium_file",
            #     "token_count": 2500,
            #     "char_count": 10000,
            #     "strategy": "standard_chunking",
            #     "message": "File (2500t) chunked with standard strategy"
            # }

        Note:
            - EMBED_WHOLE_THRESHOLD: 1000 tokens (configurable class constant)
            - Token counting uses tiktoken for accurate estimation
            - Decision is based solely on size, not content type
        """
        # Validate input
        if not text or not text.strip():
            raise ValueError(
                f"Text cannot be empty. Received empty text for file extension: {file_ext}"
            )

        # Normalize file extension
        if file_ext and not file_ext.startswith("."):
            file_ext = f".{file_ext}"
        file_ext = file_ext.lower() if file_ext else ""

        # Count tokens and characters
        token_count = self._count_tokens(text)
        char_count = len(text)

        # Decision logic: chunk if above threshold
        if token_count < self.EMBED_WHOLE_THRESHOLD:
            return {
                "should_chunk": False,
                "reason": "small_file",
                "token_count": token_count,
                "char_count": char_count,
                "strategy": "embed_whole",
                "message": (
                    f"Small document ({token_count}t < {self.EMBED_WHOLE_THRESHOLD}t), "
                    f"embedding whole without chunking"
                ),
            }
        else:
            return {
                "should_chunk": True,
                "reason": "large_or_medium_file",
                "token_count": token_count,
                "char_count": char_count,
                "strategy": "standard_chunking",
                "message": (
                    f"Large document ({token_count}t >= {self.EMBED_WHOLE_THRESHOLD}t), "
                    f"will be chunked with standard strategy"
                ),
            }

    async def generate_document_summary(
        self, full_text: str, filename: str, file_ext: str
    ) -> str:
        """
        Generate document summary using LLM with rate limiting and timeout protection.

        This method intelligently handles document summarization:
        - Small documents: Returns full text (no summarization needed)
        - Large documents: Truncates to MAX_SUMMARY_TOKENS before summarization
        - Code files: Uses code-specific summarization prompts
        - Regular documents: Uses document-specific summarization prompts

        Process:
        1. Validate input and count tokens
        2. Check if document is small enough to skip summarization
        3. Truncate if document exceeds MAX_SUMMARY_TOKENS
        4. Generate summary using LLM with appropriate prompts
        5. Return summary or full text

        Args:
            full_text: Complete document text content (required, non-empty)
            filename: Original filename (for logging and context)
            file_ext: File extension with leading dot (e.g., '.py', '.pdf', '.docx')

        Returns:
            Summary text (or full text for small documents)
            - Small docs: Returns full text unchanged
            - Large docs: Returns LLM-generated summary (typically < 500 words)

        Raises:
            ValueError: If full_text is empty or None
            SummaryGenerationError: If summary generation fails or times out

        Example:
            summary = await processor.generate_document_summary(
                full_text="Long document content...",
                filename="project_documentation.pdf",
                file_ext=".pdf"
            )

        Note:
            - Rate limited via summary_semaphore (prevents API overload)
            - Timeout protected (SUMMARY_TIMEOUT seconds)
            - Small documents (< SMALL_SUMMARY_THRESHOLD tokens) skip summarization
            - Large documents (> MAX_SUMMARY_TOKENS) are truncated before summarization
        """
        # Validate input
        if not full_text or not full_text.strip():
            raise ValueError(
                f"full_text cannot be empty. Received empty text for file: {filename}"
            )

        # Normalize file extension
        if file_ext and not file_ext.startswith("."):
            file_ext = f".{file_ext}"
        file_ext = file_ext.lower() if file_ext else ""

        # Rate limit: acquire semaphore before processing
        async with self.summary_semaphore:
            # Count tokens
            token_count = self._count_tokens(full_text)

            # Small documents: skip summarization, return full text
            if token_count < self.SMALL_SUMMARY_THRESHOLD:
                logger.info(
                    f"Document {filename} is small ({token_count}t < {self.SMALL_SUMMARY_THRESHOLD}t), "
                    f"skipping summarization and using full text"
                )
                return full_text

            # Truncate if document exceeds maximum tokens for summarization
            if token_count > self.MAX_SUMMARY_TOKENS:
                logger.info(
                    f"Truncating {filename} for summarization: "
                    f"{token_count}t -> {self.MAX_SUMMARY_TOKENS}t "
                    f"(document too large for full summarization)"
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

            # Determine content type and language for appropriate summarization
            is_code = file_ext in self.LANG_MAP
            content_type = "code file" if is_code else "document"
            language = self.LANG_MAP.get(file_ext).value if is_code else "text"

            try:
                # Build prompts based on content type
                system_prompt = f"""You are an expert document summarizer. Create a concise, informative summary of this {content_type}.

For code files: Focus on main functions, classes, logic flow, key features, and architectural patterns.
For documents: Focus on main topics, key points, structure, conclusions, and important details.

Requirements:
- Keep the summary under 500 words
- Capture all essential information
- Maintain clarity and structure
- Use appropriate technical terminology for code files"""

                user_prompt = f"""Summarize this {content_type} ({language}):

Filename: {filename}
File Extension: {file_ext}
Token Count: {actual_tokens}

Content:
{summarization_text}

Provide a clear, structured summary that captures the essential information."""

                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]

                # Generate summary with timeout protection
                logger.debug(
                    f"Generating summary for {filename} ({actual_tokens}t, "
                    f"type: {content_type}, language: {language})"
                )
                response = await asyncio.wait_for(
                    self.summarizer.ainvoke(messages), timeout=self.SUMMARY_TIMEOUT
                )

                # Extract and validate summary
                summary = (
                    response.content.strip()
                    if hasattr(response, "content")
                    else str(response).strip()
                )

                if not summary:
                    raise SummaryGenerationError(
                        f"Generated summary is empty for {filename}"
                    )

                logger.info(
                    f"Summary generated for {filename}: {len(summary)} characters "
                    f"(from {actual_tokens}t input)"
                )
                return summary

            except asyncio.TimeoutError:
                error_msg = (
                    f"Summary generation timed out after {self.SUMMARY_TIMEOUT}s "
                    f"for {filename} ({token_count}t). "
                    f"Document may be too large or LLM service is slow."
                )
                logger.error(error_msg, exc_info=True)
                raise SummaryGenerationError(error_msg)

            except SummaryGenerationError:
                # Re-raise summary errors as-is
                raise

            except Exception as e:
                error_msg = (
                    f"Summary generation failed for {filename} ({file_ext}): {str(e)}. "
                    f"Token count: {token_count}, Content type: {content_type}"
                )
                logger.error(error_msg, exc_info=True)
                raise SummaryGenerationError(error_msg)

    # ========================================================================
    # 4.5: CHUNKING & VALIDATION
    # ========================================================================

    def _validate_chunks(self, chunks: List[Document]) -> List[Document]:
        """
        Validate and track chunk quality metrics, filtering out invalid chunks.

        This method performs quality checks on document chunks and removes invalid ones:
        - Empty chunks (no content or only whitespace)
        - Very small chunks (< 50 characters) are tracked but kept
        - Calculates statistics for monitoring chunk quality

        Validation Process:
        1. Analyze all chunks for size and content
        2. Track statistics (empty, very small, average size, max size)
        3. Filter out empty/whitespace-only chunks
        4. Log statistics for monitoring

        Args:
            chunks: List of Document chunks to validate (required)

        Returns:
            Filtered list of chunks with empty/whitespace chunks removed
            Original order is preserved for valid chunks

        Raises:
            ValueError: If chunks is None (empty list is allowed)

        Example:
            chunks = [Document(page_content="..."), Document(page_content="")]
            validated = processor._validate_chunks(chunks)
            # Returns: [Document(page_content="...")]  # Empty chunk removed

        Note:
            - Empty chunks are removed (whitespace-only content)
            - Very small chunks (< 50 chars) are kept but logged
            - Statistics are logged for quality monitoring
            - Token counts are not validated here (done in chunking)
        """
        # Validate input
        if chunks is None:
            raise ValueError("chunks cannot be None (use empty list if no chunks)")

        if not chunks:
            logger.debug("No chunks to validate (empty list)")
            return []

        # Initialize statistics
        stats = {
            "total_chunks": len(chunks),
            "empty_chunks": 0,
            "very_small_chunks": 0,
            "min_chunk_size": 0,
            "avg_chunk_size": 0,
            "max_chunk_size": 0,
            "valid_chunks": 0,
        }

        sizes = []
        valid_chunks = []

        # Analyze each chunk
        for i, chunk in enumerate(chunks):
            if not isinstance(chunk, Document):
                logger.warning(
                    f"Invalid chunk type at index {i}: {type(chunk).__name__}, skipping"
                )
                stats["empty_chunks"] += 1
                continue

            content = chunk.page_content if hasattr(chunk, "page_content") else ""
            content_len = len(content)
            sizes.append(content_len)

            # Track empty chunks
            if content_len == 0 or not content.strip():
                stats["empty_chunks"] += 1
                logger.debug(f"Empty chunk detected at index {i}, will be removed")
            # Track very small chunks (but keep them)
            elif content_len < 50:
                stats["very_small_chunks"] += 1
                logger.debug(
                    f"Very small chunk at index {i}: {content_len} characters "
                    f"(may have limited context)"
                )
                valid_chunks.append(chunk)
            else:
                valid_chunks.append(chunk)

        # Calculate statistics
        if sizes:
            stats["min_chunk_size"] = min(sizes)
            stats["avg_chunk_size"] = round(sum(sizes) / len(sizes), 2)
            stats["max_chunk_size"] = max(sizes)
        stats["valid_chunks"] = len(valid_chunks)

        # Log statistics
        if stats["empty_chunks"] > 0:
            logger.warning(
                f"Chunk validation: {stats['empty_chunks']} empty chunks removed "
                f"out of {stats['total_chunks']} total"
            )

        if stats["very_small_chunks"] > 0:
            logger.info(
                f"Chunk validation: {stats['very_small_chunks']} very small chunks "
                f"(< 50 chars) detected but kept"
            )

        logger.info(
            f"Chunk validation complete: {stats['valid_chunks']}/{stats['total_chunks']} "
            f"valid chunks (avg: {stats['avg_chunk_size']} chars, "
            f"range: {stats['min_chunk_size']}-{stats['max_chunk_size']} chars)"
        )

        return valid_chunks

    def _chunk_documents(
        self, docs: List[Document], file_ext: str, strategy: str
    ) -> List[Document]:
        """
        Smart language-aware chunking with token-based splitting.

        This method intelligently chunks documents using language-specific splitters
        for code files and generic splitters for regular documents. It uses token-based
        counting for accurate size limits and adds comprehensive metadata to each chunk.

        Chunking Process:
        1. Get file-specific configuration (chunk_size, chunk_overlap)
        2. Validate overlap ratio (warns if suboptimal)
        3. Select appropriate splitter (language-aware or generic)
        4. Split documents into chunks using token counting
        5. Add metadata to each chunk (index, token count, etc.)
        6. Validate and filter chunks
        7. Return validated chunks

        Args:
            docs: List of Document objects to chunk (required, non-empty)
            file_ext: File extension with leading dot (e.g., '.py', '.pdf', '.js')
            strategy: Chunking strategy name for logging (e.g., 'standard_chunking')

        Returns:
            List of chunked Document objects with metadata:
            - chunk_index: Zero-based index of chunk
            - total_chunks: Total number of chunks
            - is_whole_document: False (chunked document)
            - chunk_token_count: Token count for this chunk

        Raises:
            ValueError: If docs is empty or None, or file_ext is invalid

        Example:
            docs = [Document(page_content="Long document text...")]
            chunks = processor._chunk_documents(
                docs=docs,
                file_ext=".py",
                strategy="standard_chunking"
            )
            # Returns: [Document(...), Document(...), ...] with metadata

        Note:
            - Uses language-specific splitters for 41+ programming languages
            - Applies token-based counting for accurate size limits
            - Validates overlap ratio (warns if < 10% or > 50%)
            - Falls back to simple chunking on errors (1000/200 default)
            - Empty chunks are automatically filtered out
        """
        # Validate input
        if not docs:
            raise ValueError(
                "docs cannot be empty. Provide at least one Document to chunk."
            )

        if not file_ext:
            raise ValueError("file_ext is required for chunking configuration")

        # Normalize file extension
        if not file_ext.startswith("."):
            file_ext = f".{file_ext}"
        file_ext = file_ext.lower()

        try:
            # Get configuration for this file type
            config = self.FILE_CONFIGS.get(
                file_ext, {"chunk_size": 1000, "chunk_overlap": 200}
            )
            chunk_size = config.get("chunk_size", 1000)
            chunk_overlap = config.get("chunk_overlap", 200)

            # Validate configuration values
            if chunk_size <= 0:
                logger.warning(
                    f"Invalid chunk_size {chunk_size} for {file_ext}, using default 1000"
                )
                chunk_size = 1000

            if chunk_overlap < 0:
                logger.warning(
                    f"Invalid chunk_overlap {chunk_overlap} for {file_ext}, using default 200"
                )
                chunk_overlap = 200

            if chunk_overlap >= chunk_size:
                logger.warning(
                    f"chunk_overlap ({chunk_overlap}) >= chunk_size ({chunk_size}) "
                    f"for {file_ext}, adjusting overlap to {chunk_size // 2}"
                )
                chunk_overlap = chunk_size // 2

            # Validate overlap ratio
            overlap_ratio = chunk_overlap / chunk_size if chunk_size > 0 else 0
            if overlap_ratio < 0.1:
                logger.warning(
                    f"Overlap ratio {overlap_ratio:.1%} is very low (< 10%) for {file_ext}. "
                    f"Consider increasing overlap for better context preservation."
                )
            elif overlap_ratio > 0.5:
                logger.warning(
                    f"Overlap ratio {overlap_ratio:.1%} is very high (> 50%) for {file_ext}. "
                    f"Consider reducing overlap to avoid excessive redundancy."
                )

            # Language-aware splitting
            lang = self.LANG_MAP.get(file_ext)

            if lang:
                logger.info(
                    f"Using {lang.value}-aware splitter for {file_ext} "
                    f"(chunk_size: {chunk_size}, overlap: {chunk_overlap})"
                )
                text_splitter = RecursiveCharacterTextSplitter.from_language(
                    language=lang,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    length_function=self._count_tokens,
                )
            else:
                logger.info(
                    f"Using generic splitter for {file_ext} "
                    f"(chunk_size: {chunk_size}, overlap: {chunk_overlap})"
                )
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    length_function=self._count_tokens,
                )

            # Split documents into chunks
            logger.debug(f"Splitting {len(docs)} document(s) into chunks...")
            chunks = text_splitter.split_documents(docs)

            if not chunks:
                logger.warning(
                    f"No chunks created from {len(docs)} document(s) for {file_ext}. "
                    f"Documents may be too small or empty."
                )
                return []

            # Add chunk metadata with token count
            for i, chunk in enumerate(chunks):
                if not hasattr(chunk, "metadata"):
                    chunk.metadata = {}

                chunk_token_count = self._count_tokens(chunk.page_content)
                chunk.metadata.update(
                    {
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "is_whole_document": False,
                        "chunk_token_count": chunk_token_count,
                        "chunk_char_count": len(chunk.page_content),
                    }
                )

            # Validate chunks (removes empty ones)
            validated_chunks = self._validate_chunks(chunks)

            if len(validated_chunks) < len(chunks):
                logger.warning(
                    f"Chunking validation removed {len(chunks) - len(validated_chunks)} "
                    f"invalid chunks from {file_ext}"
                )

            logger.info(
                f"Created {len(validated_chunks)} validated chunks from {len(docs)} "
                f"document(s) using {strategy} for {file_ext}"
            )

            return validated_chunks

        except Exception as e:
            error_msg = (
                f"Chunking failed for {file_ext} using {strategy}: {str(e)}. "
                f"Falling back to simple chunking (1000/200)."
            )
            logger.error(error_msg, exc_info=True)

            # Fallback to simple chunking with default values
            try:
                logger.info("Attempting fallback chunking with default settings")
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=1000, chunk_overlap=200
                )
                fallback_chunks = text_splitter.split_documents(docs)

                # Add basic metadata to fallback chunks
                for i, chunk in enumerate(fallback_chunks):
                    if not hasattr(chunk, "metadata"):
                        chunk.metadata = {}
                    chunk.metadata.update(
                        {
                            "chunk_index": i,
                            "total_chunks": len(fallback_chunks),
                            "is_whole_document": False,
                            "chunk_token_count": self._count_tokens(chunk.page_content),
                            "chunk_char_count": len(chunk.page_content),
                            "fallback_chunking": True,  # Mark as fallback
                        }
                    )

                validated_fallback = self._validate_chunks(fallback_chunks)
                logger.info(
                    f"Fallback chunking created {len(validated_fallback)} chunks"
                )
                return validated_fallback

            except Exception as fallback_error:
                logger.error(
                    f"Fallback chunking also failed: {fallback_error}",
                    exc_info=True,
                )
                # Return empty list if even fallback fails
                return []

    # ========================================================================
    # 4.6: DOCUMENT PROCESSING PIPELINE
    # ========================================================================
    #
    # Main processing pipeline methods:
    #   - _validate_and_normalize_doc(): Input validation
    #   - _process_single_document(): Process one document (parse → summarize → chunk → embed)
    #   - process_documents():  MAIN API - Handles single or multiple documents
    #   - process_document(): Legacy API (backwards compatibility)
    # ========================================================================

    def _validate_and_normalize_doc(
        self, doc_data: Union[Dict[str, Any], DocInfo]
    ) -> Dict[str, Any]:
        """
        Validate and normalize a single document data object.

        This method accepts either a DocInfo Pydantic model or a dictionary, validates
        all required fields, normalizes file extensions, and ensures the file type
        is supported by the processor.

        Validation Process:
        1. Convert DocInfo to dict if needed
        2. Validate required fields (filename, public_url)
        3. Normalize file extension (ensure leading dot, lowercase)
        4. Validate file type is supported
        5. Extract and normalize metadata

        Args:
            doc_data: Document data object (DocInfo model or dict) with keys:
                     - filename: Required, document filename
                     - filetype (or file_type): Optional, file extension (auto-detected from filename if missing)
                     - public_url (or s3_url or url): Required, publicly accessible URL
                     - metadata: Optional, flexible dictionary for additional info

        Returns:
            Normalized document data dictionary with keys:
            - filename: Validated filename (stripped)
            - public_url: Validated public URL
            - file_ext: Normalized file extension (with leading dot, lowercase)
            - metadata: Normalized metadata dictionary (empty dict if not provided)

        Raises:
            ValueError: If required fields are missing or file type is not supported
            TypeError: If doc_data is not a dict or DocInfo instance

        Example:
            # With DocInfo model
            doc_info = DocInfo(
                filename="document.pdf",
                filetype=".pdf",
                public_url="https://bucket.s3.amazonaws.com/doc.pdf"
            )
            normalized = processor._validate_and_normalize_doc(doc_info)

            # With dict
            normalized = processor._validate_and_normalize_doc({
                "filename": "script.py",
                "filetype": "py",
                "public_url": "https://..."
            })
        """
        # Validate input type
        if not isinstance(doc_data, (DocInfo, dict)):
            raise TypeError(
                f"doc_data must be DocInfo or dict, got {type(doc_data).__name__}"
            )

        # Convert DocInfo to dict if needed
        if isinstance(doc_data, DocInfo):
            doc_dict = {
                "filename": doc_data.filename,
                "filetype": doc_data.filetype,  # Already normalized by Pydantic
                "public_url": str(doc_data.public_url),
                "metadata": doc_data.metadata or {},
            }
        else:
            doc_dict = doc_data

        # Extract and validate filename
        filename = doc_dict.get("filename")
        if not filename:
            raise ValueError("Document data must include 'filename' field (required)")
        filename = str(filename).strip()
        if not filename:
            raise ValueError("filename cannot be empty or whitespace only")

        # Support both public_url and s3_url (backwards compatibility)
        public_url = (
            doc_dict.get("public_url") or doc_dict.get("s3_url") or doc_dict.get("url")
        )
        if not public_url:
            raise ValueError(
                "Document data must include 'public_url' (or 's3_url' or 'url') field (required)"
            )
        public_url = str(public_url).strip()
        if not public_url:
            raise ValueError("public_url cannot be empty or whitespace only")

        # Basic URL validation
        if not (public_url.startswith("http://") or public_url.startswith("https://")):
            logger.warning(
                f"public_url does not start with http:// or https://: {public_url[:50]}..."
            )

        # Get file extension from filetype or filename
        filetype = (
            doc_dict.get("filetype")
            or doc_dict.get("file_type")
            or Path(filename).suffix
        )

        # Normalize file extension
        if filetype:
            file_ext = str(filetype).lower().strip()
        else:
            file_ext = Path(filename).suffix.lower()

        # Ensure leading dot
        if file_ext and not file_ext.startswith("."):
            file_ext = f".{file_ext}"

        # Default to .txt if no extension found
        if not file_ext:
            logger.warning(
                f"No file extension found for {filename}, defaulting to .txt"
            )
            file_ext = ".txt"

        # Validate file type is supported
        if file_ext not in self.FILE_CONFIGS:
            supported_formats = sorted(self.FILE_CONFIGS.keys())
            raise ValueError(
                f"File type '{file_ext}' is not supported for {filename}. "
                f"Supported formats: {supported_formats}"
            )

        # Get and normalize metadata
        metadata = doc_dict.get("metadata", {})
        if metadata is None:
            metadata = {}
        elif not isinstance(metadata, dict):
            logger.warning(f"metadata is not a dict for {filename}, converting to dict")
            metadata = {"raw_metadata": metadata}

        logger.debug(
            f"Validated document: {filename} ({file_ext}) from {public_url[:50]}..."
        )

        return {
            "filename": filename,
            "public_url": public_url,
            "file_ext": file_ext,
            "metadata": metadata,
        }

    async def _process_single_document(
        self,
        doc_data: Dict[str, Any],
        session_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Process a single document through the full RAG pipeline.

        This method orchestrates the complete document processing workflow:
        1. Parse document from remote URL
        2. Generate summary (in parallel with chunking)
        3. Decide chunking strategy (embed whole vs chunk)
        4. Chunk document if needed
        5. Store chunks in vector store
        6. Return comprehensive result

        Pipeline Flow:
        Parse → Summary (parallel) → Chunk Decision → Chunking → Embedding → Storage

        Args:
            doc_data: Normalized document data dictionary (from _validate_and_normalize_doc)
                     Must contain: filename, public_url, file_ext, metadata
            session_id: Session identifier (required, for tracking)
            user_id: User identifier (required, for tracking)

        Returns:
            Processing result dictionary with keys:
            - success: bool - Whether processing succeeded
            - filename: str - Document filename
            - file_type: str - File extension (without dot)
            - is_code_file: bool - Whether file is a code file
            - total_chunks: int - Number of chunks created
            - chunk_ids: List[str] - Vector store chunk IDs
            - token_count: int - Total tokens in document
            - char_count: int - Total characters in document
            - summary: str - Generated summary
            - language: str - Detected language (for code files)
            - chunking_strategy: str - Strategy used ('embed_whole' or 'standard_chunking')
            - is_whole_document: bool - Whether document was embedded whole
            - session_id: str - Session identifier
            - user_id: str - User identifier
            - session_metadata: dict - Complete session metadata
            - message: str - Human-readable status message
            - error: str - Error message (if success=False)
            - error_type: str - Error type name (if success=False)

        Raises:
            ValueError: If doc_data is missing required fields
            DocumentLoadError: If document parsing fails (caught and returned as error)

        Example:
            result = await processor._process_single_document(
                doc_data={
                    "filename": "document.pdf",
                    "public_url": "https://...",
                    "file_ext": ".pdf",
                    "metadata": {}
                },
                session_id="thread_123",
                user_id="user_456"
            )
        """
        # Validate input
        if not doc_data:
            raise ValueError("doc_data cannot be empty")

        filename = doc_data.get("filename")
        public_url = doc_data.get("public_url")
        file_ext = doc_data.get("file_ext")
        metadata = doc_data.get("metadata", {})

        if not all([filename, public_url, file_ext]):
            raise ValueError("doc_data must contain filename, public_url, and file_ext")

        if not session_id:
            raise ValueError("session_id is required")
        if not user_id:
            raise ValueError("user_id is required")

        logger.info(f"Processing single document: {filename} ({file_ext})")

        try:
            # 1. PARSE DOCUMENT
            parsed_text = await self._parse_document(public_url, file_ext, filename)

            if not parsed_text or not parsed_text.strip():
                raise DocumentLoadError(f"No content parsed from {filename}")

            logger.info(f"Parsed {filename}: {len(parsed_text)} characters")

            # 2. CREATE DOCUMENT OBJECT
            doc = Document(
                page_content=parsed_text,
                metadata={
                    "source": public_url,
                    "filename": filename,
                },
            )

            # 3. PARALLEL PROCESSING: Summary generation, chunking decision, and chunking
            # Run these in parallel for better performance
            decision = self._should_chunk_document(parsed_text, file_ext)
            logger.info(f"Decision: {decision['message']}")

            # Prepare metadata
            is_code = file_ext.lower() in self.LANG_MAP
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

            session_metadata = {
                "session_id": session_id,
                "user_id": user_id,
                "filename": filename,
                "file_type": file_ext[1:],
                "public_url": public_url,
                "processed_at": datetime.now().isoformat(),
                "is_code_file": is_code,
                "token_count": decision["token_count"],
                "char_count": decision["char_count"],
                "chunking_strategy": decision["strategy"],
                "language": (
                    self.LANG_MAP.get(file_ext.lower()).value if is_code else None
                ),
                "total_chunks": 0,
            }

            if metadata:
                chunk_metadata.update(metadata)
                session_metadata.update(metadata)

            doc.metadata.update(chunk_metadata)

            # Start summary generation task (runs in parallel with chunking, embedding, and storage)
            summary_task = asyncio.create_task(
                self.generate_document_summary(parsed_text, filename, file_ext)
            )

            if not decision["should_chunk"]:
                # SMALL: Embed whole
                doc.metadata.update(
                    {
                        "chunk_index": 0,
                        "total_chunks": 1,
                        "is_whole_document": True,
                    }
                )
                chunks = [doc]
                logger.info(f"Embedding whole document")
            else:
                # Run blocking chunking in thread pool (summary generation continues in background)
                chunks = await asyncio.to_thread(
                    self._chunk_documents, [doc], file_ext, decision["strategy"]
                )

            # Filter out empty chunks (summary generation continues in background)
            chunks = [c for c in chunks if c.page_content.strip()]

            if not chunks:
                raise ValueError(f"No valid content after splitting {filename}")

            logger.info(f"Final chunk count: {len(chunks)} valid chunks")

            # 4. SAFETY CHECK - Truncate chunks that are too large (summary generation continues in background)
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

            # 5. STORE IN VECTOR STORE (summary generation continues in background during embedding/storage)
            logger.info(f"Storing {len(chunks)} chunks...")
            chunk_ids = await asyncio.to_thread(self.vector_store.add_documents, chunks)
            logger.info(f"Stored {len(chunk_ids)} chunks")

            session_metadata["total_chunks"] = len(chunks)

            # 6. Wait for summary to complete (only now, after all other operations)
            summary_text = await summary_task
            # Note: summary_text is NOT stored in session_metadata to avoid duplication
            # It's only returned in the final result

            return {
                "success": True,
                "filename": filename,
                "file_type": file_ext[1:],
                "is_code_file": is_code,
                "total_chunks": len(chunks),
                "chunk_ids": chunk_ids,
                "token_count": decision["token_count"],
                "char_count": decision["char_count"],
                "summary": summary_text,
                "language": session_metadata.get("language"),
                "chunking_strategy": decision["strategy"],
                "is_whole_document": not decision["should_chunk"],
                "session_id": session_id,
                "user_id": user_id,
                "session_metadata": session_metadata,
                "message": f"Success: {filename}: {len(chunks)} chunks | Summary: {len(summary_text)} chars",
            }

        except DocumentLoadError as e:
            error_msg = f"Document loading failed for {filename}: {str(e)}"
            logger.error(error_msg, exc_info=True)
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
        except ValueError as e:
            error_msg = f"Validation error for {filename}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {
                "success": False,
                "filename": filename,
                "file_type": file_ext[1:] if file_ext else "unknown",
                "error": str(e),
                "error_type": "ValueError",
                "session_id": session_id,
                "user_id": user_id,
                "message": f"Failed: {filename} - Validation error",
            }
        except Exception as e:
            error_msg = f"Unexpected error processing {filename}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {
                "success": False,
                "filename": filename,
                "file_type": file_ext[1:] if file_ext else "unknown",
                "error": str(e),
                "error_type": type(e).__name__,
                "session_id": session_id,
                "user_id": user_id,
                "message": f"Failed: {filename} - {type(e).__name__}",
            }

    async def _process_documents_with_batch(
        self,
        normalized_docs: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Process multiple documents using batch parsing for optimal performance.

        This method leverages batch parsing to group documents by loader type and
        processes them efficiently:
        - LlamaParse docs: Single batch API call for all PDFs/Office docs (80% cost reduction)
        - Text docs: Parallel text loading for all code files
        - Post-parsing: All documents processed in parallel (summarize, chunk, embed)

        Processing Flow:
        1. Batch parse all documents (grouped by loader type)
        2. Process each parsed result in parallel (summarize, chunk, embed)
        3. Handle exceptions and return results in original order

        Performance Benefits:
        - 5 PDFs: 1 API call instead of 5 (80% cost reduction)
        - Total time: ~7s vs ~25s (4x faster for multiple documents)
        - Parallel processing: All post-parsing steps run simultaneously

        Args:
            normalized_docs: List of validated document data dictionaries
                           Each dict must contain: filename, public_url, file_ext, metadata
            session_id: Session identifier (required, for tracking)
            user_id: User identifier (required, for tracking)

        Returns:
            List of processing result dictionaries (same order as input)
            Each result has the same structure as _process_single_document() returns

        Raises:
            ValueError: If normalized_docs is empty or session_id/user_id missing

        Example:
            results = await processor._process_documents_with_batch(
                normalized_docs=[
                    {"filename": "doc1.pdf", "public_url": "...", "file_ext": ".pdf"},
                    {"filename": "doc2.py", "public_url": "...", "file_ext": ".py"}
                ],
                session_id="thread_123",
                user_id="user_456"
            )
        """
        # Validate input
        if not normalized_docs:
            raise ValueError("normalized_docs cannot be empty")
        if not session_id:
            raise ValueError("session_id is required")
        if not user_id:
            raise ValueError("user_id is required")

        logger.info(
            f"Processing {len(normalized_docs)} documents with batch optimization"
        )

        # Step 1: Batch parse all documents
        logger.info(
            f"Step 1/3: Batch parsing {len(normalized_docs)} documents "
            "(grouped by loader type for efficiency)"
        )

        parse_input = [
            {
                "public_url": doc["public_url"],
                "file_ext": doc["file_ext"],
                "filename": doc["filename"],
            }
            for doc in normalized_docs
        ]

        try:
            parsed_results = await self._parse_documents_batch(parse_input)
        except Exception as e:
            logger.error(f"Batch parsing failed: {e}", exc_info=True)
            # Fallback to individual processing if batch fails
            logger.warning("Falling back to individual document processing")
            tasks = [
                self._process_single_document(doc, session_id, user_id)
                for doc in normalized_docs
            ]
            return await asyncio.gather(*tasks, return_exceptions=True)

        # Step 2: Process all parsed documents in parallel
        logger.info("Step 2/3: Processing parsed documents (summarize, chunk, embed)")

        async def process_parsed_doc(doc_data, parsed_result):
            """Process a single parsed document"""
            filename = doc_data["filename"]
            file_ext = doc_data["file_ext"]
            public_url = doc_data["public_url"]
            metadata = doc_data.get("metadata", {})
            parsed_text = parsed_result.get("parsed_text", "")

            # Check for parsing errors
            if parsed_result.get("error") or not parsed_text.strip():
                return {
                    "success": False,
                    "filename": filename,
                    "file_type": file_ext[1:] if file_ext else "unknown",
                    "error": parsed_result.get("error", "No content parsed"),
                    "error_type": "DocumentLoadError",
                    "session_id": session_id,
                    "user_id": user_id,
                    "message": f"Failed: {filename} - Parsing error",
                }

            try:
                logger.info(
                    f"Processing parsed {filename}: {len(parsed_text)} characters"
                )

                # Create Document object
                doc = Document(
                    page_content=parsed_text,
                    metadata={
                        "source": public_url,
                        "filename": filename,
                    },
                )

                # Chunking decision
                decision = self._should_chunk_document(parsed_text, file_ext)
                logger.info(f"{filename}: {decision['message']}")

                # Prepare metadata
                is_code = file_ext.lower() in self.LANG_MAP
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

                session_metadata = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "filename": filename,
                    "file_type": file_ext[1:],
                    "public_url": public_url,
                    "processed_at": datetime.now().isoformat(),
                    "is_code_file": is_code,
                    "token_count": decision["token_count"],
                    "char_count": decision["char_count"],
                    "chunking_strategy": decision["strategy"],
                    "language": (
                        self.LANG_MAP.get(file_ext.lower()).value if is_code else None
                    ),
                    "total_chunks": 0,
                }

                if metadata:
                    chunk_metadata.update(metadata)
                    session_metadata.update(metadata)

                doc.metadata.update(chunk_metadata)

                # Start summary generation task (runs in parallel)
                summary_task = asyncio.create_task(
                    self.generate_document_summary(parsed_text, filename, file_ext)
                )

                # Chunk document
                if not decision["should_chunk"]:
                    doc.metadata.update(
                        {
                            "chunk_index": 0,
                            "total_chunks": 1,
                            "is_whole_document": True,
                        }
                    )
                    chunks = [doc]
                else:
                    chunks = await asyncio.to_thread(
                        self._chunk_documents, [doc], file_ext, decision["strategy"]
                    )

                # Filter empty chunks
                chunks = [c for c in chunks if c.page_content.strip()]

                if not chunks:
                    raise ValueError(f"No valid content after splitting {filename}")

                # Safety check - truncate oversized chunks
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

                # Store in vector store
                chunk_ids = await asyncio.to_thread(
                    self.vector_store.add_documents, chunks
                )

                session_metadata["total_chunks"] = len(chunks)

                # Wait for summary
                summary_text = await summary_task

                return {
                    "success": True,
                    "filename": filename,
                    "file_type": file_ext[1:],
                    "is_code_file": is_code,
                    "total_chunks": len(chunks),
                    "chunk_ids": chunk_ids,
                    "token_count": decision["token_count"],
                    "char_count": decision["char_count"],
                    "summary": summary_text,
                    "language": session_metadata.get("language"),
                    "chunking_strategy": decision["strategy"],
                    "is_whole_document": not decision["should_chunk"],
                    "session_id": session_id,
                    "user_id": user_id,
                    "session_metadata": session_metadata,
                    "message": f"Success: {filename}: {len(chunks)} chunks",
                }

            except Exception as e:
                logger.error(f"Processing failed for {filename}: {e}", exc_info=True)
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

        # Process all parsed documents in parallel
        tasks = [
            process_parsed_doc(doc_data, parsed_result)
            for doc_data, parsed_result in zip(normalized_docs, parsed_results)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Step 3: Handle exceptions and return results
        logger.info("Step 3/3: Finalizing results")

        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Document {i} processing failed: {result}", exc_info=True)
                processed_results.append(
                    {
                        "success": False,
                        "filename": normalized_docs[i]["filename"],
                        "error": str(result),
                        "error_type": type(result).__name__,
                        "session_id": session_id,
                        "user_id": user_id,
                        "message": f"Failed: {normalized_docs[i]['filename']}",
                    }
                )
            else:
                processed_results.append(result)

        # Log summary
        success_count = sum(1 for r in processed_results if r.get("success"))
        failed_count = len(processed_results) - success_count

        if failed_count > 0:
            logger.warning(
                f"Batch processing complete: {success_count}/{len(processed_results)} succeeded, "
                f"{failed_count} failed"
            )
        else:
            logger.info(
                f"Batch processing complete: {success_count}/{len(processed_results)} succeeded"
            )

        return processed_results

    async def process_documents(
        self,
        docs: Union[Dict[str, Any], List[Dict[str, Any]], DocInfo, List[DocInfo]],
        session_id: str,
        user_id: str,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Main API: Process single or multiple documents with intelligent optimization.

        This is the primary entry point for document processing. It automatically
        optimizes processing based on the number of documents:
        - Single document: Standard flow (no batch overhead)
        - Multiple documents: Batch parsing optimization (4x faster, 80% cost reduction)

        The method accepts DocInfo models or dictionaries, validates all inputs,
        and returns comprehensive processing results.

        Processing Pipeline:
        1. Validate and normalize all documents
        2. Route to appropriate processor (single vs batch)
        3. Handle exceptions and return results

        Args:
            docs: Single document or list of documents. Can be:
                  - DocInfo model or dict (single document)
                  - List[DocInfo] or List[dict] (multiple documents)
                  Each doc should have: filename, filetype (or file_type),
                  public_url (or s3_url), metadata (optional)
            session_id: Session identifier (required, for tracking and retrieval)
            user_id: User identifier (required, for tracking and retrieval)

        Returns:
            - Single document: Dict with processing result
            - Multiple documents: List[Dict] with processing results (same order as input)

            Result structure (see _process_single_document for details):
            - success: bool
            - filename: str
            - total_chunks: int
            - summary: str
            - error: str (if success=False)
            - ... (see _process_single_document docstring)

        Raises:
            ValueError: If docs is empty, session_id/user_id missing, or validation fails

        Example:
            # Single document with DocInfo
            doc = DocInfo(
                filename="document.pdf",
                filetype=".pdf",
                public_url="https://bucket.s3.amazonaws.com/document.pdf"
            )
            result = await processor.process_documents(
                docs=doc,
                session_id="thread_123",
                user_id="user_456"
            )

            # Multiple documents with dicts
            results = await processor.process_documents(
                docs=[
                    {"filename": "doc1.pdf", "filetype": ".pdf", "public_url": "https://..."},
                    {"filename": "doc2.py", "filetype": ".py", "public_url": "https://..."}
                ],
                session_id="thread_123",
                user_id="user_456"
            )
        """
        # Validate session_id and user_id
        if not session_id:
            raise ValueError("session_id is required")
        if not user_id:
            raise ValueError("user_id is required")

        # Normalize to list (handle both single and multiple, DocInfo and dict)
        if isinstance(docs, (DocInfo, dict)):
            docs_list = [docs]
            is_single = True
        elif isinstance(docs, list):
            docs_list = docs
            is_single = False
        else:
            raise TypeError(
                f"docs must be DocInfo, dict, List[DocInfo], or List[dict], "
                f"got {type(docs).__name__}"
            )

        if not docs_list:
            raise ValueError("No documents provided (docs list is empty)")

        # Validate and normalize all documents
        normalized_docs = []
        validation_errors = []

        for i, doc_data in enumerate(docs_list):
            try:
                normalized = self._validate_and_normalize_doc(doc_data)
                normalized_docs.append(normalized)
            except Exception as e:
                error_msg = f"Failed to validate document {i}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                validation_errors.append((i, str(e), doc_data))

                # For single document, raise immediately
                if is_single:
                    raise ValueError(f"Document validation failed: {str(e)}") from e
                # For multiple documents, continue but track errors
                continue

        if not normalized_docs:
            if validation_errors:
                error_summary = "; ".join(
                    [f"Doc {i}: {err}" for i, err, _ in validation_errors]
                )
                raise ValueError(
                    f"No valid documents to process. Validation errors: {error_summary}"
                )
            else:
                raise ValueError("No valid documents to process")

        logger.info(f"Processing {len(normalized_docs)} document(s)")

        # ========================================================================
        # OPTIMIZATION: Use batch parsing for multiple documents (4x faster!)
        # ========================================================================
        if len(normalized_docs) > 1:
            logger.info(
                f"Using batch processing for {len(normalized_docs)} documents "
                "(groups by loader type, reduces API calls)"
            )
            results = await self._process_documents_with_batch(
                normalized_docs, session_id, user_id
            )
        else:
            # Single document - use standard flow (no batch overhead)
            logger.info("Processing single document (standard flow)")
            result = await self._process_single_document(
                normalized_docs[0], session_id, user_id
            )
            results = [result]

        # Handle exceptions in results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Document {i} processing failed: {result}", exc_info=True)
                processed_results.append(
                    {
                        "success": False,
                        "filename": normalized_docs[i]["filename"],
                        "error": str(result),
                        "error_type": type(result).__name__,
                        "session_id": session_id,
                        "user_id": user_id,
                        "message": f"Failed: {normalized_docs[i]['filename']}",
                    }
                )
            else:
                processed_results.append(result)

        # Return single result or list based on input
        if is_single:
            if not processed_results:
                logger.error("No results returned for single document processing")
                return {
                    "success": False,
                    "error": "No documents processed - unexpected error",
                    "error_type": "ProcessingError",
                    "session_id": session_id,
                    "user_id": user_id,
                    "message": "Processing failed with no result",
                }
            return processed_results[0]
        else:
            # Multiple documents - return list (may include failures)
            if not processed_results:
                logger.warning("No results returned for batch processing")
                return [
                    {
                        "success": False,
                        "error": "Processing failed with no result",
                        "error_type": "ProcessingError",
                        "session_id": session_id,
                        "user_id": user_id,
                        "message": f"Failed: {doc.get('filename', 'unknown')}",
                    }
                    for doc in normalized_docs
                ]
            return processed_results

    # ========================================================================
    # 4.7: SEARCH & RETRIEVAL METHODS
    # ========================================================================
    #
    # RAG-focused methods for retrieving processed documents:
    #   - search_documents(): Semantic search with formatted results
    #   - retrieve_relevant_chunks(): Raw documents for RAG pipelines
    #   - list_session_documents(): List all docs in a session
    # ========================================================================

    async def search_documents(
        self,
        query: str,
        session_id: str,
        max_results: int = 5,
        file_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search with formatted results.

        Search documents in a session using vector similarity search. Returns
        formatted dictionaries with chunk content and metadata for easy consumption.

        Search Process:
        1. Validate input parameters
        2. Perform vector similarity search with session filtering
        3. Optionally filter by file type
        4. Format results with metadata
        5. Return top N results

        Args:
            query: Search query text (required, non-empty)
            session_id: Session/thread ID to filter documents (required, non-empty)
            max_results: Maximum number of results to return (default: 5, min: 1, max: 100)
            file_type: Optional filter by file type (e.g., 'pdf', 'py', '.pdf', '.py')
                      Accepts with or without leading dot

        Returns:
            List of formatted result dictionaries containing:
            - content: str - Chunk text content
            - filename: str - Original filename
            - file_type: str - File extension (without dot)
            - language: Optional[str] - Programming language (if code file)
            - chunk_index: Optional[int] - Index of this chunk (0-based)
            - total_chunks: Optional[int] - Total chunks in document
            - is_code_file: bool - Whether this is a code file
            - is_whole_document: bool - Whether chunk is entire document

        Raises:
            ValueError: If query or session_id is empty, or max_results is invalid
            Exception: If vector store search fails

        Example:
            # Search all documents
            results = await processor.search_documents(
                query="How to implement authentication?",
                session_id="thread_123",
                max_results=5
            )

            # Search only Python files
            results = await processor.search_documents(
                query="authentication",
                session_id="thread_123",
                max_results=10,
                file_type="py"
            )

            for result in results:
                print(f"{result['filename']}: {result['content'][:100]}...")
        """
        # Validate input
        if not query or not query.strip():
            raise ValueError("query cannot be empty or whitespace only")
        query = query.strip()

        if not session_id or not session_id.strip():
            raise ValueError("session_id cannot be empty or whitespace only")
        session_id = session_id.strip()

        if not isinstance(max_results, int) or max_results < 1:
            raise ValueError(
                f"max_results must be a positive integer, got {max_results}"
            )
        if max_results > 100:
            logger.warning(
                f"max_results ({max_results}) exceeds recommended limit (100), "
                f"capping at 100 for performance"
            )
            max_results = 100

        # Normalize file_type if provided
        normalized_file_type = None
        if file_type:
            normalized_file_type = str(file_type).strip().lower()
            # Remove leading dot if present for comparison
            if normalized_file_type.startswith("."):
                normalized_file_type = normalized_file_type[1:]

        try:
            # Filter by session_id to get only docs from this thread
            pre_filter = {"session_id": {"$eq": session_id}}

            # Search with 2x buffer to account for file_type filtering
            # This ensures we get enough results after filtering
            search_k = max_results * 2 if normalized_file_type else max_results

            logger.debug(
                f"Searching documents: query='{query[:50]}...', "
                f"session_id={session_id}, max_results={max_results}, "
                f"file_type={normalized_file_type or 'all'}"
            )

            results = await asyncio.to_thread(
                self.vector_store.similarity_search,
                query=query,
                k=search_k,
                pre_filter=pre_filter,
            )

            # Optional: Filter by file type
            if normalized_file_type:
                original_count = len(results)
                results = [
                    doc
                    for doc in results
                    if doc.metadata.get("file_type", "").lower() == normalized_file_type
                ]
                filtered_count = len(results)
                if filtered_count < original_count:
                    logger.debug(
                        f"File type filter '{normalized_file_type}': "
                        f"{filtered_count}/{original_count} results matched"
                    )

            # Trim to max_results
            results = results[:max_results]

            # Format results for easy consumption
            formatted_results = []
            for doc in results:
                if not hasattr(doc, "page_content") or not hasattr(doc, "metadata"):
                    logger.warning(
                        "Invalid document structure in search results, skipping"
                    )
                    continue

                formatted_results.append(
                    {
                        "content": doc.page_content,
                        "filename": doc.metadata.get("filename", "unknown"),
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
                f"Found {len(formatted_results)} relevant chunks for query: "
                f"'{query[:50]}{'...' if len(query) > 50 else ''}' "
                f"(session: {session_id}, file_type: {normalized_file_type or 'all'})"
            )
            return formatted_results

        except ValueError:
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            error_msg = (
                f"Document search failed for query '{query[:50]}...' "
                f"in session {session_id}: {str(e)}"
            )
            logger.error(error_msg, exc_info=True)
            raise Exception(error_msg) from e

    async def retrieve_relevant_chunks(
        self, query: str, session_id: str, max_chunks: int = 5
    ) -> List[Document]:
        """
        Retrieve raw documents for RAG pipelines.

        Retrieve relevant document chunks as LangChain Document objects for direct
        integration into RAG chains. This method is designed for RAG workflows where
        you need raw Document objects with full metadata.

        Key Features:
        - Returns raw LangChain Document objects (not formatted dicts)
        - Graceful error handling (returns [] instead of raising)
        - Session-filtered results
        - Ideal for feeding into RAG chains or LLM context

        Args:
            query: Search query text (required, non-empty)
            session_id: Session/thread ID to filter documents (required, non-empty)
            max_chunks: Maximum number of chunks to return (default: 5, min: 1, max: 50)

        Returns:
            List of LangChain Document objects with full metadata.
            Returns empty list on error to avoid breaking RAG flow.

        Note:
            - Uses vector similarity search with session filtering
            - Returns raw Document objects (not formatted dicts)
            - Graceful error handling (returns [] instead of raising)
            - Ideal for feeding into RAG chains or LLM context
            - Each Document has page_content and metadata fields

        Example:
            # Retrieve chunks for RAG
            docs = await processor.retrieve_relevant_chunks(
                query="authentication implementation",
                session_id="thread_123",
                max_chunks=5
            )

            # Use in RAG chain
            context = "\n\n".join([doc.page_content for doc in docs])
            metadata_list = [doc.metadata for doc in docs]

            # Feed to LLM
            response = await llm.ainvoke(f"Context: {context}\n\nQuestion: {query}")
        """
        # Validate input
        if not query or not query.strip():
            logger.warning(
                "Empty query provided to retrieve_relevant_chunks, returning empty list"
            )
            return []

        query = query.strip()

        if not session_id or not session_id.strip():
            logger.warning(
                "Empty session_id provided to retrieve_relevant_chunks, returning empty list"
            )
            return []

        session_id = session_id.strip()

        if not isinstance(max_chunks, int) or max_chunks < 1:
            logger.warning(
                f"Invalid max_chunks ({max_chunks}), using default 5. "
                f"max_chunks must be a positive integer."
            )
            max_chunks = 5

        if max_chunks > 50:
            logger.warning(
                f"max_chunks ({max_chunks}) exceeds recommended limit (50) for RAG, "
                f"capping at 50 for performance"
            )
            max_chunks = 50

        try:
            # Filter by session_id
            pre_filter = {"session_id": {"$eq": session_id}}

            logger.debug(
                f"Retrieving chunks for RAG: query='{query[:50]}...', "
                f"session_id={session_id}, max_chunks={max_chunks}"
            )

            # Vector similarity search
            results = await asyncio.to_thread(
                self.vector_store.similarity_search,
                query=query,
                k=max_chunks,
                pre_filter=pre_filter,
            )

            # Validate results structure
            valid_results = []
            for doc in results:
                if not isinstance(doc, Document):
                    logger.warning("Invalid document type in search results, skipping")
                    continue
                if not hasattr(doc, "page_content") or not hasattr(doc, "metadata"):
                    logger.warning("Document missing required fields, skipping")
                    continue
                valid_results.append(doc)

            logger.info(
                f"Retrieved {len(valid_results)} relevant chunks for RAG | "
                f"Query: '{query[:50]}{'...' if len(query) > 50 else ''}' | "
                f"Session: {session_id}"
            )
            return valid_results

        except Exception as e:
            error_msg = (
                f"Chunk retrieval failed for query '{query[:50]}...' "
                f"in session {session_id}: {str(e)}"
            )
            logger.error(error_msg, exc_info=True)
            # Return empty list instead of raising to avoid breaking RAG flow
            return []

    async def list_session_documents(self, session_id: str) -> List[Dict[str, Any]]:
        """
        List all documents in a session with metadata.

        Get metadata for all documents uploaded in a session, deduplicated by filename.
        This method provides an overview of all documents processed in a session.

        Process:
        1. Query vector store for all chunks in session
        2. Deduplicate by filename (one entry per document)
        3. Extract and format metadata
        4. Return list of document summaries

        Args:
            session_id: Session/thread ID to query (required, non-empty)

        Returns:
            List of document metadata dictionaries containing:
            - filename: str - Original filename
            - file_type: Optional[str] - File extension (without dot)
            - language: Optional[str] - Programming language (if code file)
            - is_code_file: bool - Whether file is a code file
            - total_chunks: Optional[int] - Number of chunks for this document
            - session_id: str - Session identifier

        Note:
            - Queries vector store with empty string (inefficient, see TODO)
            - Limited to 1000 chunks per session (may miss documents if > 1000 chunks)
            - Automatically deduplicates by filename
            - Returns empty list on error or if session_id is invalid

        TODO:
            Use metadata-only query if vector store supports it:
            vector_store.get_by_metadata(filter={"session_id": session_id})
            This would be more efficient than similarity_search with empty query.

        Example:
            # List all documents in a session
            docs = await processor.list_session_documents("thread_123")
            for doc in docs:
                print(f"{doc['filename']}: {doc['total_chunks']} chunks")
                print(f"Type: {doc['file_type']}, Language: {doc['language']}")

            # Filter code files
            code_files = [d for d in docs if d['is_code_file']]
            print(f"Found {len(code_files)} code files")
        """
        # Validate input
        if not session_id or not session_id.strip():
            logger.warning(
                "Empty session_id provided to list_session_documents, returning empty list"
            )
            return []

        session_id = session_id.strip()

        try:
            pre_filter = {"session_id": {"$eq": session_id}}

            logger.debug(f"Listing documents for session: {session_id}")

            # Get all chunks from session
            # Note: Using empty query is inefficient but necessary if vector store
            # doesn't support metadata-only queries
            results = await asyncio.to_thread(
                self.vector_store.similarity_search,
                query="",  # Empty query to get all documents (inefficient)
                k=1000,  # Large number to get all docs (may miss if > 1000 chunks)
                pre_filter=pre_filter,
            )

            if not results:
                logger.info(f"No documents found in session {session_id}")
                return []

            # Deduplicate by filename and collect metadata
            seen_files = {}
            for doc in results:
                if not hasattr(doc, "metadata"):
                    logger.warning("Document missing metadata, skipping")
                    continue

                filename = doc.metadata.get("filename")
                if not filename:
                    logger.debug("Document missing filename in metadata, skipping")
                    continue

                # If we've seen this filename, update total_chunks if needed
                if filename in seen_files:
                    # Update total_chunks to the maximum (most accurate)
                    existing_total = seen_files[filename].get("total_chunks", 0)
                    current_total = doc.metadata.get("total_chunks", 0)
                    if current_total and (
                        not existing_total or current_total > existing_total
                    ):
                        seen_files[filename]["total_chunks"] = current_total
                else:
                    # First time seeing this filename
                    seen_files[filename] = {
                        "filename": filename,
                        "file_type": doc.metadata.get("file_type"),
                        "language": doc.metadata.get("language"),
                        "is_code_file": doc.metadata.get("is_code_file", False),
                        "total_chunks": doc.metadata.get("total_chunks"),
                        "session_id": session_id,
                    }

            documents = list(seen_files.values())

            # Sort by filename for consistent output
            documents.sort(key=lambda x: x.get("filename", ""))

            logger.info(
                f"Found {len(documents)} unique documents in session {session_id} "
                f"(from {len(results)} total chunks)"
            )

            # Warn if we might have hit the limit
            if len(results) >= 1000:
                logger.warning(
                    f"Hit 1000 chunk limit for session {session_id}. "
                    f"Some documents may be missing. Consider using metadata-only query."
                )

            return documents

        except Exception as e:
            error_msg = (
                f"Failed to list session documents for session {session_id}: {str(e)}"
            )
            logger.error(error_msg, exc_info=True)
            return []
