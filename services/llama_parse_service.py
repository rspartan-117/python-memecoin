import os
import logging
from typing import Any, List, Optional, Union
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Try to import LlamaParse, but gracefully handle broken llama-cloud package
try:
    from llama_cloud_services import LlamaParse
    from llama_cloud_services.parse.utils import ResultType
    LLAMA_PARSE_AVAILABLE = True
    logger.info("LlamaParse imported successfully")
except (ImportError, ModuleNotFoundError) as e:
    logger.warning(f"LlamaParse not available: {e}. Document parsing will be disabled.")
    LLAMA_PARSE_AVAILABLE = False
    LlamaParse = None
    ResultType = None

SUPPORTED_EXTENSIONS = {
    # Base types
    ".pdf",
    # Documents and presentations
    ".602",
    ".abw",
    ".cgm",
    ".cwk",
    ".doc",
    ".docx",
    ".docm",
    ".dot",
    ".dotm",
    ".hwp",
    ".key",
    ".lwp",
    ".mw",
    ".mcw",
    ".pages",
    ".pbd",
    ".ppt",
    ".pptm",
    ".pptx",
    ".pot",
    ".potm",
    ".potx",
    ".rtf",
    ".sda",
    ".sdd",
    ".sdp",
    ".sdw",
    ".sgl",
    ".sti",
    ".sxi",
    ".sxw",
    ".stw",
    ".sxg",
    ".txt",
    ".uof",
    ".uop",
    ".uot",
    ".vor",
    ".wpd",
    ".wps",
    ".xml",
    ".zabw",
    ".epub",
    ".htm",
    ".html",
    # Spreadsheets
    ".xlsx",
    ".xls",
    ".xlsm",
    ".xlsb",
    ".xlw",
    ".csv",
    ".dif",
    ".sylk",
    ".slk",
    ".prn",
    ".numbers",
    ".et",
    ".ods",
    ".fods",
    ".uos1",
    ".uos2",
    ".dbf",
    ".wk1",
    ".wk2",
    ".wk3",
    ".wk4",
    ".wks",
    ".123",
    ".wq1",
    ".wq2",
    ".wb1",
    ".wb2",
    ".wb3",
    ".qpw",
    ".xlr",
    ".eth",
    ".tsv",
}


class LlamaParseService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        result_type: Optional[Any] = None,
    ):
        """
        Initialize Llama Parse Service.

        Args:
            api_key: Llama Cloud API key. If not provided, reads from LLAMA_CLOUD_API_KEY env var.
            result_type: Output format (default: MD for markdown)
        """
        if not LLAMA_PARSE_AVAILABLE:
            logger.warning("LlamaParseService initialized but LlamaParse is not available due to package errors")
            self.parser = None
            return
            
        api_key = api_key or os.getenv("LLAMA_CLOUD_API_KEY")
        if not api_key:
            logger.warning(
                "LLAMA_CLOUD_API_KEY not set. Document parsing will not function."
            )
            self.parser = None
            return

        try:
            # Use ResultType.MD if available, otherwise use string "markdown"
            if result_type is None:
                result_type = ResultType.MD if ResultType else "markdown"
            
            self.parser = LlamaParse(
                api_key=api_key,
                result_type=result_type,
                verbose=True,
                num_workers=4,
                split_by_page=True,
                page_separator="\n\n---\n\n",
            )
            logger.info("LlamaParseService initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize LlamaParse: {e}")
            self.parser = None

    def is_supported_format(self, file_path: str) -> bool:
        """
        Check if file extension is supported by LlamaParse.

        Args:
            file_path: Path to file (local or temp)

        Returns:
            True if format is supported by LlamaParse, False otherwise
        """
        ext = Path(file_path).suffix.lower()
        return ext in SUPPORTED_EXTENSIONS

    def _extract_text(self, result: Any) -> str:
        """
        Extract clean text from LlamaParse result.
        Handles both single Document and list of Documents/Pages.

        Args:
            result: Result from parser.aparse() - can be Document, list of Documents, or Page objects

        Returns:
            Clean text string (Markdown when result_type=MD)
        """
        # Log result structure for debugging
        logger.debug(f"Result type: {type(result)}")
        logger.debug(
            f"Result attributes: {dir(result) if hasattr(result, '__dict__') else 'N/A'}"
        )

        # Handle case where result has a 'pages' attribute (common with split_by_page=True)
        if hasattr(result, "pages"):
            logger.debug(f"Result has .pages attribute, extracting pages")
            docs = result.pages if isinstance(result.pages, list) else [result.pages]
        # Handle both single Document and list of Documents
        elif not isinstance(result, list):
            docs = [result]
        else:
            docs = result

        logger.debug(f"Processing {len(docs)} document(s)/page(s)")

        # Extract .text (which is MD when result_type=MD)
        texts = []
        for i, doc in enumerate(docs):
            # Log for debugging during development
            if i == 0:  # Only log first item to avoid spam
                logger.debug(f"Document {i} type: {type(doc)}")
                logger.debug(f"Has .text? {hasattr(doc, 'text')}")
                logger.debug(f"Has .md? {hasattr(doc, 'md')}")

            # Try different attribute names based on llama-cloud-services version
            if hasattr(doc, "text"):
                texts.append(doc.text)
            elif hasattr(doc, "md"):
                texts.append(doc.md)
            elif isinstance(doc, dict) and "text" in doc:
                texts.append(doc["text"])
            elif isinstance(doc, dict) and "md" in doc:
                texts.append(doc["md"])
            else:
                # Fallback: convert to string
                logger.warning(
                    f"Unknown document structure for item {i}, using str() fallback"
                )
                texts.append(str(doc))

        # Join all pages/documents
        result_text = "\n\n".join(texts)
        logger.debug(
            f"Extracted {len(result_text)} characters from {len(texts)} page(s)"
        )

        # Validate result is not empty
        if not result_text.strip():
            logger.warning(
                "Extracted text is empty - this may indicate a parsing issue"
            )

        return result_text

    def _validate_file_path(self, file_path: str) -> None:
        """
        Validate a single file path.

        Args:
            file_path: File path to validate

        Raises:
            ValueError: If file path is invalid or not supported
        """
        if not file_path or not isinstance(file_path, str):
            raise ValueError(f"Invalid file path: {file_path}")

        if not file_path.strip():
            raise ValueError("File path cannot be empty")

        if not os.path.exists(file_path):
            raise ValueError(f"File not found: {file_path}")

        if not self.is_supported_format(file_path):
            ext = Path(file_path).suffix.lower()
            raise ValueError(
                f"File format '{ext}' is not supported by LlamaParse. "
                f"Supported extensions: {sorted(SUPPORTED_EXTENSIONS)}"
            )

    def _validate_file_paths(self, file_paths: List[str]) -> None:
        """
        Validate that all file paths exist and are supported by LlamaParse.

        Args:
            file_paths: List of file paths to validate

        Raises:
            ValueError: If any file path is invalid or not supported
        """
        for file_path in file_paths:
            self._validate_file_path(file_path)

    async def parse_single_file(self, file_path: str) -> str:
        """
        Parse a single file using Llama Cloud API (async).

        Args:
            file_path: Path to the file to parse

        Returns:
            Parsed text content (markdown format)

        Raises:
            ValueError: If file doesn't exist or format is not supported
            Exception: If parsing fails
        """
        if not LLAMA_PARSE_AVAILABLE or self.parser is None:
            logger.warning(f"Cannot parse {file_path}: LlamaParse not available")
            raise Exception("LlamaParse service is not available due to package errors")
            
        # Validate file path
        self._validate_file_path(file_path)

        try:
            logger.info(f"Parsing single file with LlamaParse: {file_path}")
            result = await self.parser.aparse(file_path)
            logger.info(f"Job metadata: {result.job_metadata}")
            # Debug logging
            logger.debug(f"Raw result type: {type(result)}")
            if isinstance(result, list) and len(result) > 0:
                logger.debug(f"First item type: {type(result[0])}")
                logger.debug(f"List length: {len(result)}")

            # Extract clean text using our helper method
            parsed_text = self._extract_text(result)

            logger.info(
                f"Successfully parsed {file_path}: {len(parsed_text)} characters"
            )
            return parsed_text

        except ValueError:
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            error_msg = f"Failed to parse file {file_path}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise Exception(error_msg)

    async def parse_multiple_files(self, file_paths: List[str]) -> List[str]:
        """
        Parse multiple files using Llama Cloud API (async batch processing).

        Args:
            file_paths: List of file paths to parse

        Returns:
            List of parsed text content (markdown format) in the same order as input

        Raises:
            ValueError: If any file doesn't exist or format is not supported
            Exception: If parsing fails
        """
        if not LLAMA_PARSE_AVAILABLE or self.parser is None:
            logger.warning(f"Cannot parse files: LlamaParse not available")
            raise Exception("LlamaParse service is not available due to package errors")
            
        if not file_paths:
            raise ValueError("File paths list cannot be empty")

        # Validate all file paths
        self._validate_file_paths(file_paths)

        try:
            logger.info(f"Parsing {len(file_paths)} files with LlamaParse (batch)")
            results = await self.parser.aparse(file_paths)

            # Extract text from each result
            parsed_results = []
            for i, result in enumerate(results):
                # Extract clean text using our helper method
                parsed_text = self._extract_text(result)
                parsed_results.append(parsed_text)
                logger.info(
                    f"Successfully parsed {file_paths[i]}: {len(parsed_text)} characters"
                )

            logger.info(f"Successfully parsed {len(parsed_results)} files")
            return parsed_results

        except ValueError:
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            error_msg = f"Failed to parse files: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise Exception(error_msg)

    async def parse(self, file_paths: Union[str, List[str]]) -> Union[str, List[str]]:
        """
        Unified parsing method that handles both single file and multiple files.

        Args:
            file_paths: Single file path (str) or list of file paths (List[str])

        Returns:
            Parsed text (str) for single file, or list of parsed texts (List[str]) for multiple files

        Raises:
            ValueError: If file doesn't exist or format is not supported
            Exception: If parsing fails
        """
        if isinstance(file_paths, str):
            # Single file
            return await self.parse_single_file(file_paths)
        elif isinstance(file_paths, list):
            # Multiple files
            return await self.parse_multiple_files(file_paths)
        else:
            raise TypeError(
                f"file_paths must be str or List[str], got {type(file_paths)}"
            )
