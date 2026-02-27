"""
Test LlamaParseService with actual PDF parsing and save results to markdown files.

This script tests:
1. Single file parsing
2. Multiple file parsing
3. Saves parsed results to markdown files

Usage:
    python test/test_llama_parse_service_parsing.py
"""

import asyncio
import os
import sys
import logging
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.llama_parse_service import LlamaParseService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_single_file_parse():
    """Test parsing a single PDF file."""
    logger.info("=" * 80)
    logger.info("TEST 1: Single File Parse")
    logger.info("=" * 80)

    try:
        # Initialize service
        service = LlamaParseService()
        
        # Test file
        test_file = "2501.12948v1.pdf"
        
        if not os.path.exists(test_file):
            logger.error(f"❌ Test file not found: {test_file}")
            return None
        
        logger.info(f"Parsing single file: {test_file}")
        
        # Parse the file
        parsed_text = await service.parse_single_file(test_file)
        
        logger.info(f"✅ Successfully parsed {test_file}")
        logger.info(f"   Parsed text length: {len(parsed_text)} characters")
        logger.info(f"   First 200 characters: {parsed_text[:200]}...")
        
        # Save to markdown file
        output_file = f"test/parsed_single_{Path(test_file).stem}.md"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# Parsed Content: {test_file}\n\n")
            f.write(f"**Parsed at:** {datetime.now().isoformat()}\n\n")
            f.write(f"**File:** {test_file}\n\n")
            f.write("---\n\n")
            f.write(parsed_text)
        
        logger.info(f"✅ Saved parsed content to: {output_file}")
        
        return parsed_text
        
    except Exception as e:
        logger.error(f"❌ Failed to parse single file: {str(e)}", exc_info=True)
        return None


async def test_multiple_files_parse():
    """Test parsing multiple PDF files."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: Multiple Files Parse (Batch)")
    logger.info("=" * 80)

    try:
        # Initialize service
        service = LlamaParseService()
        
        # Test files
        test_files = [
            "2501.12948v1.pdf",
            "1706.03762v7.pdf"
        ]
        
        # Check if files exist
        missing_files = [f for f in test_files if not os.path.exists(f)]
        if missing_files:
            logger.error(f"❌ Test files not found: {missing_files}")
            return None
        
        logger.info(f"Parsing {len(test_files)} files: {test_files}")
        
        # Parse multiple files
        parsed_texts = await service.parse_multiple_files(test_files)
        
        logger.info(f"✅ Successfully parsed {len(parsed_texts)} files")
        
        # Save each parsed result to a markdown file
        for i, (test_file, parsed_text) in enumerate(zip(test_files, parsed_texts)):
            logger.info(f"   File {i+1}: {test_file} - {len(parsed_text)} characters")
            
            output_file = f"test/parsed_batch_{Path(test_file).stem}.md"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(f"# Parsed Content: {test_file}\n\n")
                f.write(f"**Parsed at:** {datetime.now().isoformat()}\n\n")
                f.write(f"**File:** {test_file}\n\n")
                f.write(f"**Batch position:** {i+1} of {len(test_files)}\n\n")
                f.write("---\n\n")
                f.write(parsed_text)
            
            logger.info(f"   ✅ Saved to: {output_file}")
        
        # Also save a combined file
        combined_file = "test/parsed_batch_combined.md"
        with open(combined_file, "w", encoding="utf-8") as f:
            f.write(f"# Combined Parsed Content (Batch)\n\n")
            f.write(f"**Parsed at:** {datetime.now().isoformat()}\n\n")
            f.write(f"**Files:** {', '.join(test_files)}\n\n")
            f.write("---\n\n")
            
            for i, (test_file, parsed_text) in enumerate(zip(test_files, parsed_texts)):
                f.write(f"## File {i+1}: {test_file}\n\n")
                f.write(parsed_text)
                f.write("\n\n---\n\n")
        
        logger.info(f"✅ Saved combined content to: {combined_file}")
        
        return parsed_texts
        
    except Exception as e:
        logger.error(f"❌ Failed to parse multiple files: {str(e)}", exc_info=True)
        return None


async def test_unified_parse():
    """Test the unified parse method with both single and multiple files."""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: Unified Parse Method")
    logger.info("=" * 80)

    try:
        service = LlamaParseService()
        
        # Test single file via unified method
        single_file = "2501.12948v1.pdf"
        if os.path.exists(single_file):
            logger.info(f"Testing unified parse with single file: {single_file}")
            result = await service.parse(single_file)
            logger.info(f"✅ Unified parse (single): {len(result)} characters")
        
        # Test multiple files via unified method
        multiple_files = ["2501.12948v1.pdf", "1706.03762v7.pdf"]
        if all(os.path.exists(f) for f in multiple_files):
            logger.info(f"Testing unified parse with multiple files: {multiple_files}")
            results = await service.parse(multiple_files)
            logger.info(f"✅ Unified parse (multiple): {len(results)} files")
            for i, r in enumerate(results):
                logger.info(f"   File {i+1}: {len(r)} characters")
        
    except Exception as e:
        logger.error(f"❌ Unified parse test failed: {str(e)}", exc_info=True)


async def main():
    """Main test function."""
    logger.info("=" * 80)
    logger.info("LlamaParseService - Parsing Test Suite")
    logger.info("=" * 80)
    
    # Check API key
    api_key = os.getenv("LLAMA_CLOUD_API_KEY")
    if not api_key:
        logger.error("❌ LLAMA_CLOUD_API_KEY not set in environment")
        logger.error("   Please set the API key before running tests")
        return
    
    logger.info("✅ API key found in environment")
    
    # Test 1: Single file parse
    single_result = await test_single_file_parse()
    
    # Test 2: Multiple files parse
    multiple_results = await test_multiple_files_parse()
    
    # Test 3: Unified parse method
    await test_unified_parse()
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    
    if single_result:
        logger.info("✅ Single file parse: PASSED")
    else:
        logger.error("❌ Single file parse: FAILED")
    
    if multiple_results:
        logger.info(f"✅ Multiple files parse: PASSED ({len(multiple_results)} files)")
    else:
        logger.error("❌ Multiple files parse: FAILED")
    
    logger.info("\nCheck the 'test/' directory for output markdown files:")
    logger.info("  - parsed_single_*.md")
    logger.info("  - parsed_batch_*.md")
    logger.info("  - parsed_batch_combined.md")


if __name__ == "__main__":
    asyncio.run(main())

