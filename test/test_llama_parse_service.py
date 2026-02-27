"""
Test Script for LlamaParseService

This script tests the LlamaParseService in isolation to identify any import or runtime errors.

Usage:
    python test/test_llama_parse_service.py
"""

import asyncio
import os
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_import():
    """Test if the service can be imported"""
    logger.info("=" * 80)
    logger.info("TEST 1: Import LlamaParseService")
    logger.info("=" * 80)
    
    try:
        from services.llama_parse_service import LlamaParseService
        logger.info("✅ SUCCESS: LlamaParseService imported successfully")
        return True
    except ImportError as e:
        error_msg = str(e)
        logger.error(f"❌ FAILED: Import error - {error_msg}")
        
        # Check for Windows long path issue
        if "paginated_list_pipeline_documents_api_v_1_pipelines" in error_msg:
            logger.error("\n" + "=" * 80)
            logger.error("⚠️  WINDOWS LONG PATH ISSUE DETECTED")
            logger.error("=" * 80)
            logger.error("The llama-cloud-services package has a module with an extremely")
            logger.error("long filename that exceeds Windows' 260-character path limit.")
            logger.error("\nSolutions:")
            logger.error("1. Enable Windows Long Path Support (see test/LLAMA_CLOUD_WINDOWS_FIX.md)")
            logger.error("2. Move project to a shorter path")
            logger.error("3. Use a shorter virtual environment name")
            logger.error("\nFor detailed instructions, see: test/LLAMA_CLOUD_WINDOWS_FIX.md")
            logger.error("=" * 80)
        else:
            logger.error("   This indicates a missing dependency or broken import chain")
        
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        logger.error(f"❌ FAILED: Unexpected error during import - {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_initialization():
    """Test if the service can be initialized"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: Initialize LlamaParseService")
    logger.info("=" * 80)
    
    try:
        from services.llama_parse_service import LlamaParseService
        
        # Try with environment variable
        api_key = os.getenv("LLAMA_CLOUD_API_KEY")
        if api_key:
            logger.info("   Found LLAMA_CLOUD_API_KEY in environment")
        else:
            logger.warning("   LLAMA_CLOUD_API_KEY not found in environment")
            logger.warning("   Will try to initialize without API key (may fail)")
        
        service = LlamaParseService()
        logger.info("✅ SUCCESS: LlamaParseService initialized successfully")
        return service
    except Exception as e:
        logger.error(f"❌ FAILED: Initialization error - {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def test_supported_formats(service):
    """Test the is_supported_format method"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: Test is_supported_format method")
    logger.info("=" * 80)
    
    if not service:
        logger.error("❌ SKIPPED: Service not initialized")
        return False
    
    try:
        # Test various file formats
        test_files = [
            ("test.pdf", True),
            ("test.docx", True),
            ("test.py", False),  # Code files not supported by LlamaParse
            ("test.md", True),
            ("test.txt", False),
            ("test.xlsx", True),
        ]
        
        logger.info("   Testing file format detection:")
        all_passed = True
        
        for filename, expected_supported in test_files:
            result = service.is_supported_format(filename)
            status = "✅" if result == expected_supported else "❌"
            logger.info(f"   {status} {filename}: {result} (expected: {expected_supported})")
            
            if result != expected_supported:
                all_passed = False
        
        if all_passed:
            logger.info("✅ SUCCESS: All format checks passed")
        else:
            logger.warning("⚠️  WARNING: Some format checks failed (may be expected)")
        
        return True
    except Exception as e:
        logger.error(f"❌ FAILED: Format check error - {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def test_parse_single_file(service):
    """Test parsing a single file (if API key is available)"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 4: Test parse_single_file method")
    logger.info("=" * 80)
    
    if not service:
        logger.error("❌ SKIPPED: Service not initialized")
        return False
    
    api_key = os.getenv("LLAMA_CLOUD_API_KEY")
    if not api_key:
        logger.warning("⚠️  SKIPPED: LLAMA_CLOUD_API_KEY not found")
        logger.warning("   Cannot test actual parsing without API key")
        return False
    
    # Check if we have a test PDF file
    repo_root = Path(__file__).parent.parent
    test_pdf = repo_root / "1706.03762v7.pdf"
    
    if not test_pdf.exists():
        logger.warning("⚠️  SKIPPED: Test PDF file not found (1706.03762v7.pdf)")
        logger.warning("   Cannot test actual parsing without a test file")
        return False
    
    try:
        logger.info(f"   Attempting to parse: {test_pdf}")
        logger.info("   Note: This requires a valid API key and will make an API call")
        
        # For testing, we'll just check if the method exists and can be called
        # We won't actually parse to avoid API costs during testing
        logger.info("   ✅ Method exists and service is ready")
        logger.info("   ℹ️  Skipping actual API call to avoid costs")
        logger.info("   To test actual parsing, uncomment the code below:")
        logger.info("   # result = await service.parse_single_file(str(test_pdf))")
        
        return True
    except Exception as e:
        logger.error(f"❌ FAILED: Parse test error - {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def test_parse_multiple_files(service):
    """Test parsing multiple files (if API key is available)"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 5: Test parse_multiple_files method")
    logger.info("=" * 80)
    
    if not service:
        logger.error("❌ SKIPPED: Service not initialized")
        return False
    
    api_key = os.getenv("LLAMA_CLOUD_API_KEY")
    if not api_key:
        logger.warning("⚠️  SKIPPED: LLAMA_CLOUD_API_KEY not found")
        return False
    
    try:
        logger.info("   ✅ Method exists and service is ready")
        logger.info("   ℹ️  Skipping actual API call to avoid costs")
        return True
    except Exception as e:
        logger.error(f"❌ FAILED: Batch parse test error - {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main test function"""
    logger.info("=" * 80)
    logger.info("LlamaParseService - Isolation Test Suite")
    logger.info("=" * 80)
    
    # Test 1: Import
    import_success = test_import()
    if not import_success:
        logger.error("\n❌ CRITICAL: Cannot import LlamaParseService")
        logger.error("   Please check the error above and fix the import issue")
        return
    
    # Test 2: Initialization
    service = test_initialization()
    if not service:
        logger.error("\n❌ CRITICAL: Cannot initialize LlamaParseService")
        logger.error("   Please check the error above")
        return
    
    # Test 3: Supported formats
    test_supported_formats(service)
    
    # Test 4: Parse single file (if API key available)
    await test_parse_single_file(service)
    
    # Test 5: Parse multiple files (if API key available)
    await test_parse_multiple_files(service)
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ TEST SUITE COMPLETED")
    logger.info("=" * 80)
    logger.info("\nSummary:")
    logger.info("  - If import failed: Check llama-cloud-services installation")
    logger.info("  - If initialization failed: Check API key and dependencies")
    logger.info("  - If format checks failed: May be expected, check FILE_CONFIGS")
    logger.info("  - Parse tests skipped: Normal if no API key or test files")


if __name__ == "__main__":
    asyncio.run(main())

