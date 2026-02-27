"""
Test Script for DocumentProcessor V1

This script tests the new DocumentProcessor with:
- 2 code files from the repo
- 2 PDF files (1706.03762v7.pdf, 2501.12948v1.pdf)
- Markdown files from the repo
- Both single and batch processing

Usage:
    python test/test_document_processor_v1.py
"""

import asyncio
import os
import sys
import logging
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from threading import Thread
from typing import List, Dict, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from processors.document_processor_v1 import DocumentProcessor, DocInfo

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class LocalFileServer:
    """Simple HTTP server to serve local files for testing"""

    def __init__(self, port: int = 8000, directory: str = "."):
        self.port = port
        self.directory = directory
        self.server = None
        self.thread = None

    def start(self):
        """Start the HTTP server in a background thread"""
        handler = SimpleHTTPRequestHandler
        handler.directory = self.directory

        self.server = HTTPServer(("localhost", self.port), handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"Started local file server on http://localhost:{self.port}")

    def stop(self):
        """Stop the HTTP server"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("Stopped local file server")

    def get_url(self, file_path: str) -> str:
        """Get HTTP URL for a local file"""
        # Convert to relative path from server directory
        abs_path = Path(file_path).resolve()
        server_dir = Path(self.directory).resolve()
        
        try:
            rel_path = abs_path.relative_to(server_dir)
            # Use forward slashes for URL
            url_path = rel_path.as_posix().replace("\\", "/")
            return f"http://localhost:{self.port}/{url_path}"
        except ValueError:
            # File is outside server directory, try to make it work
            # by using the absolute path (may not work, but worth trying)
            url_path = abs_path.as_posix().replace("\\", "/")
            logger.warning(
                f"File {file_path} is outside server directory {self.directory}, "
                f"using absolute path in URL (may not work)"
            )
            return f"http://localhost:{self.port}/{url_path}"


def find_test_files() -> Dict[str, List[str]]:
    """Find test files in the repository"""
    repo_root = Path(__file__).parent.parent
    
    files = {
        "code": [],
        "markdown": [],
        "pdf": [],
    }
    
    # Find code files (Python)
    code_files = [
        "processors/document_processor_v1.py",
        "services/llama_parse_service.py",
    ]
    
    for code_file in code_files:
        file_path = repo_root / code_file
        if file_path.exists() and file_path.is_file():
            files["code"].append(str(file_path.resolve()))
            logger.debug(f"Found code file: {file_path}")
        else:
            logger.warning(f"Code file not found: {file_path}")
    
    # Find markdown files
    markdown_files = [
        "README.md",
        "CODE_ORGANIZATION_GUIDE.md",
    ]
    
    for md_file in markdown_files:
        file_path = repo_root / md_file
        if file_path.exists() and file_path.is_file():
            files["markdown"].append(str(file_path.resolve()))
            logger.debug(f"Found markdown file: {file_path}")
        else:
            logger.warning(f"Markdown file not found: {file_path}")
    
    # Find PDF files
    pdf_files = [
        "1706.03762v7.pdf",
        "2501.12948v1.pdf",
    ]
    
    for pdf_file in pdf_files:
        file_path = repo_root / pdf_file
        if file_path.exists() and file_path.is_file():
            files["pdf"].append(str(file_path.resolve()))
            logger.debug(f"Found PDF file: {file_path}")
        else:
            logger.warning(f"PDF file not found: {file_path}")
    
    return files


async def test_single_document(
    processor: DocumentProcessor,
    server: LocalFileServer,
    file_path: str,
    file_type: str,
    session_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Test processing a single document"""
    file_name = Path(file_path).name
    file_ext = Path(file_path).suffix
    
    logger.info(f"\n{'='*80}")
    logger.info(f"Testing SINGLE document: {file_name} ({file_ext})")
    logger.info(f"{'='*80}")
    
    # Get URL from server
    file_url = server.get_url(file_path)
    
    # Create DocInfo model
    doc_info = DocInfo(
        filename=file_name,
        filetype=file_ext,
        public_url=file_url,
        metadata={"test": True, "file_type_category": file_type},
    )
    
    try:
        result = await processor.process_documents(
            docs=doc_info,
            session_id=session_id,
            user_id=user_id,
        )
        
        logger.info(f"\n✅ SUCCESS: {file_name}")
        logger.info(f"   - Total chunks: {result.get('total_chunks', 0)}")
        logger.info(f"   - Token count: {result.get('token_count', 0)}")
        logger.info(f"   - Summary length: {len(result.get('summary', ''))} chars")
        logger.info(f"   - Is code file: {result.get('is_code_file', False)}")
        logger.info(f"   - Chunking strategy: {result.get('chunking_strategy', 'unknown')}")
        logger.info(f"   - Is whole document: {result.get('is_whole_document', False)}")
        
        return result
        
    except Exception as e:
        logger.error(f"\n❌ FAILED: {file_name}")
        logger.error(f"   Error: {str(e)}", exc_info=True)
        return {"success": False, "error": str(e), "filename": file_name}


async def test_batch_documents(
    processor: DocumentProcessor,
    server: LocalFileServer,
    file_paths: List[str],
    file_types: List[str],
    session_id: str,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Test processing multiple documents in batch"""
    logger.info(f"\n{'='*80}")
    logger.info(f"Testing BATCH processing: {len(file_paths)} documents")
    logger.info(f"{'='*80}")
    
    # Create DocInfo models for all files
    docs = []
    for file_path, file_type in zip(file_paths, file_types):
        file_name = Path(file_path).name
        file_ext = Path(file_path).suffix
        
        file_url = server.get_url(file_path)
        
        doc_info = DocInfo(
            filename=file_name,
            filetype=file_ext,
            public_url=file_url,
            metadata={"test": True, "file_type_category": file_type},
        )
        docs.append(doc_info)
    
    try:
        results = await processor.process_documents(
            docs=docs,
            session_id=session_id,
            user_id=user_id,
        )
        
        logger.info(f"\n✅ BATCH PROCESSING COMPLETE")
        logger.info(f"   - Total documents: {len(results)}")
        
        success_count = sum(1 for r in results if r.get("success", False))
        logger.info(f"   - Successful: {success_count}/{len(results)}")
        
        for i, result in enumerate(results):
            filename = result.get("filename", f"doc_{i}")
            if result.get("success"):
                logger.info(f"\n   ✅ {filename}:")
                logger.info(f"      - Chunks: {result.get('total_chunks', 0)}")
                logger.info(f"      - Tokens: {result.get('token_count', 0)}")
                logger.info(f"      - Strategy: {result.get('chunking_strategy', 'unknown')}")
            else:
                logger.error(f"\n   ❌ {filename}:")
                logger.error(f"      - Error: {result.get('error', 'Unknown error')}")
        
        return results
        
    except Exception as e:
        logger.error(f"\n❌ BATCH PROCESSING FAILED")
        logger.error(f"   Error: {str(e)}", exc_info=True)
        return [{"success": False, "error": str(e)}]


async def test_search(
    processor: DocumentProcessor,
    session_id: str,
    query: str = "document processing",
    max_results: int = 5,
):
    """Test document search functionality"""
    logger.info(f"\n{'='*80}")
    logger.info(f"Testing SEARCH: '{query}'")
    logger.info(f"{'='*80}")
    
    try:
        results = await processor.search_documents(
            query=query,
            session_id=session_id,
            max_results=max_results,
        )
        
        logger.info(f"\n✅ SEARCH SUCCESS")
        logger.info(f"   - Found {len(results)} results")
        
        for i, result in enumerate(results, 1):
            logger.info(f"\n   Result {i}:")
            logger.info(f"      - Filename: {result.get('filename', 'unknown')}")
            logger.info(f"      - File type: {result.get('file_type', 'unknown')}")
            logger.info(f"      - Content preview: {result.get('content', '')[:100]}...")
            logger.info(f"      - Chunk index: {result.get('chunk_index', 'N/A')}/{result.get('total_chunks', 'N/A')}")
        
        return results
        
    except Exception as e:
        logger.error(f"\n❌ SEARCH FAILED")
        logger.error(f"   Error: {str(e)}", exc_info=True)
        return []


async def test_list_documents(
    processor: DocumentProcessor,
    session_id: str,
):
    """Test listing documents in a session"""
    logger.info(f"\n{'='*80}")
    logger.info(f"Testing LIST DOCUMENTS for session: {session_id}")
    logger.info(f"{'='*80}")
    
    try:
        documents = await processor.list_session_documents(session_id=session_id)
        
        logger.info(f"\n✅ LIST SUCCESS")
        logger.info(f"   - Found {len(documents)} documents")
        
        for doc in documents:
            logger.info(f"\n   - {doc.get('filename', 'unknown')}:")
            logger.info(f"      - File type: {doc.get('file_type', 'unknown')}")
            logger.info(f"      - Total chunks: {doc.get('total_chunks', 0)}")
            logger.info(f"      - Is code file: {doc.get('is_code_file', False)}")
            logger.info(f"      - Language: {doc.get('language', 'N/A')}")
        
        return documents
        
    except Exception as e:
        logger.error(f"\n❌ LIST FAILED")
        logger.error(f"   Error: {str(e)}", exc_info=True)
        return []


async def main():
    """Main test function"""
    logger.info("=" * 80)
    logger.info("DocumentProcessor V1 - Comprehensive Test Suite")
    logger.info("=" * 80)
    
    # Initialize processor
    logger.info("\nInitializing DocumentProcessor...")
    processor = DocumentProcessor()
    logger.info("✅ DocumentProcessor initialized")
    
    # Start local file server
    repo_root = Path(__file__).parent.parent
    server = LocalFileServer(port=8000, directory=str(repo_root))
    server.start()
    
    # Wait a moment for server to start
    await asyncio.sleep(1)
    
    try:
        # Find test files
        test_files = find_test_files()
        
        logger.info("\n" + "=" * 80)
        logger.info("Test Files Found:")
        logger.info("=" * 80)
        logger.info(f"  Code files: {len(test_files['code'])}")
        for f in test_files["code"]:
            logger.info(f"    - {Path(f).name}")
        logger.info(f"  Markdown files: {len(test_files['markdown'])}")
        for f in test_files["markdown"]:
            logger.info(f"    - {Path(f).name}")
        logger.info(f"  PDF files: {len(test_files['pdf'])}")
        for f in test_files["pdf"]:
            logger.info(f"    - {Path(f).name}")
        
        # Check if we have any files to test
        total_files = sum(len(files) for files in test_files.values())
        if total_files == 0:
            logger.error("\n❌ No test files found! Please ensure:")
            logger.error("   - Code files exist in processors/ or services/")
            logger.error("   - Markdown files exist in repo root")
            logger.error("   - PDF files (1706.03762v7.pdf, 2501.12948v1.pdf) exist in repo root")
            return
        
        # Test session IDs
        session_id_single = "test_session_single"
        session_id_batch = "test_session_batch"
        user_id = "test_user"
        
        # ========================================================================
        # TEST 1: Single Document Processing - Code Files
        # ========================================================================
        if test_files["code"]:
            logger.info("\n\n" + "=" * 80)
            logger.info("TEST 1: Single Document Processing - Code Files")
            logger.info("=" * 80)
            
            for code_file in test_files["code"][:2]:  # Test first 2 code files
                await test_single_document(
                    processor=processor,
                    server=server,
                    file_path=code_file,
                    file_type="code",
                    session_id=session_id_single,
                    user_id=user_id,
                )
                await asyncio.sleep(1)  # Small delay between tests
        
        # ========================================================================
        # TEST 2: Single Document Processing - PDF Files
        # ========================================================================
        if test_files["pdf"]:
            logger.info("\n\n" + "=" * 80)
            logger.info("TEST 2: Single Document Processing - PDF Files")
            logger.info("=" * 80)
            
            for pdf_file in test_files["pdf"]:
                await test_single_document(
                    processor=processor,
                    server=server,
                    file_path=pdf_file,
                    file_type="pdf",
                    session_id=session_id_single,
                    user_id=user_id,
                )
                await asyncio.sleep(1)
        
        # ========================================================================
        # TEST 3: Single Document Processing - Markdown Files
        # ========================================================================
        if test_files["markdown"]:
            logger.info("\n\n" + "=" * 80)
            logger.info("TEST 3: Single Document Processing - Markdown Files")
            logger.info("=" * 80)
            
            for md_file in test_files["markdown"][:2]:  # Test first 2 markdown files
                await test_single_document(
                    processor=processor,
                    server=server,
                    file_path=md_file,
                    file_type="markdown",
                    session_id=session_id_single,
                    user_id=user_id,
                )
                await asyncio.sleep(1)
        
        # ========================================================================
        # TEST 4: Batch Processing - Mixed File Types
        # ========================================================================
        logger.info("\n\n" + "=" * 80)
        logger.info("TEST 4: Batch Processing - Mixed File Types")
        logger.info("=" * 80)
        
        # Prepare batch files: 2 code files + 2 PDFs + 2 markdown files
        batch_files = []
        batch_types = []
        
        if test_files["code"]:
            batch_files.extend(test_files["code"][:2])
            batch_types.extend(["code"] * min(2, len(test_files["code"])))
        
        if test_files["pdf"]:
            batch_files.extend(test_files["pdf"][:2])
            batch_types.extend(["pdf"] * min(2, len(test_files["pdf"])))
        
        if test_files["markdown"]:
            batch_files.extend(test_files["markdown"][:2])
            batch_types.extend(["markdown"] * min(2, len(test_files["markdown"])))
        
        if batch_files:
            await test_batch_documents(
                processor=processor,
                server=server,
                file_paths=batch_files,
                file_types=batch_types,
                session_id=session_id_batch,
                user_id=user_id,
            )
        
        # ========================================================================
        # TEST 5: Search Documents
        # ========================================================================
        logger.info("\n\n" + "=" * 80)
        logger.info("TEST 5: Search Documents")
        logger.info("=" * 80)
        
        await test_search(
            processor=processor,
            session_id=session_id_batch,
            query="document processing and chunking",
            max_results=5,
        )
        
        # ========================================================================
        # TEST 6: List Session Documents
        # ========================================================================
        logger.info("\n\n" + "=" * 80)
        logger.info("TEST 6: List Session Documents")
        logger.info("=" * 80)
        
        await test_list_documents(
            processor=processor,
            session_id=session_id_batch,
        )
        
        logger.info("\n\n" + "=" * 80)
        logger.info("✅ ALL TESTS COMPLETED")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"\n❌ TEST SUITE FAILED: {str(e)}", exc_info=True)
    finally:
        # Stop server
        server.stop()
        logger.info("\nTest server stopped")


if __name__ == "__main__":
    asyncio.run(main())

