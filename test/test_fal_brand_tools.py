"""
Quick verification script to test Fal.ai and Brand.dev tools imports
"""

import sys
import os
import logging

# Add parent directory to path to import from tools
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_imports():
    """Test that all new tools can be imported successfully."""
    
    print("\n" + "="*60)
    print("Testing Fal.ai and Brand.dev Tools Import")
    print("="*60 + "\n")
    
    # Add parent to path
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    
    # Test Fal Generation Tools - Three separate files
    try:
        # Import the three separate tool modules directly
        import importlib.util
        
        tools_dir = os.path.join(os.path.dirname(__file__), '..', 'tools')
        
        # First load the helper module (to avoid __init__.py)
        helper_path = os.path.join(tools_dir, 'fal_api_helper.py')
        spec_helper = importlib.util.spec_from_file_location("fal_api_helper", helper_path)
        helper_module = importlib.util.module_from_spec(spec_helper)
        sys.modules['tools.fal_api_helper'] = helper_module  # Register it
        spec_helper.loader.exec_module(helper_module)
        
        # Load context and agent_state modules (dependencies)
        context_path = os.path.join(os.path.dirname(__file__), '..', 'context', 'runtime_context.py')
        if os.path.exists(context_path):
            spec_ctx = importlib.util.spec_from_file_location("runtime_context", context_path)
            ctx_module = importlib.util.module_from_spec(spec_ctx)
            sys.modules['context.runtime_context'] = ctx_module
            spec_ctx.loader.exec_module(ctx_module)
        
        agent_state_path = os.path.join(os.path.dirname(__file__), '..', 'agent_state', 'state.py')
        if os.path.exists(agent_state_path):
            spec_state = importlib.util.spec_from_file_location("agent_state", agent_state_path)
            state_module = importlib.util.module_from_spec(spec_state)
            sys.modules['agent_state'] = state_module
            spec_state.loader.exec_module(state_module)
        
        # Load text-to-image tool
        text_to_img_path = os.path.join(tools_dir, 'fal_text_to_image_tool.py')
        spec1 = importlib.util.spec_from_file_location("fal_text_to_image_tool", text_to_img_path)
        text_to_img_module = importlib.util.module_from_spec(spec1)
        spec1.loader.exec_module(text_to_img_module)
        
        # Load img-to-img tool
        img_to_img_path = os.path.join(tools_dir, 'fal_img_to_img_tool.py')
        spec2 = importlib.util.spec_from_file_location("fal_img_to_img_tool", img_to_img_path)
        img_to_img_module = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(img_to_img_module)
        
        # Load remove bg tool
        remove_bg_path = os.path.join(tools_dir, 'fal_remove_bg_tool.py')
        spec3 = importlib.util.spec_from_file_location("fal_remove_bg_tool", remove_bg_path)
        remove_bg_module = importlib.util.module_from_spec(spec3)
        spec3.loader.exec_module(remove_bg_module)
        
        print("✓ Fal generation tool modules loaded (3 separate files)")
        
        # Check tools exist
        fal_tools = [
            text_to_img_module.generate_image_text_to_image,
            img_to_img_module.generate_image_img_to_img,
            remove_bg_module.remove_background_from_image,
        ]
        print(f"  - Found {len(fal_tools)} Fal.ai tools:")
        for tool in fal_tools:
            print(f"    • {tool.name}")
            
    except Exception as e:
        print(f"✗ Failed to load Fal Generation Tools: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test Brand Data Tools - Import module file directly
    try:
        brand_path = os.path.join(
            os.path.dirname(__file__), 
            '..', 
            'tools', 
            'brand_data_tools.py'
        )
        spec = importlib.util.spec_from_file_location("brand_data_tools", brand_path)
        brand_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(brand_module)
        
        print("\n✓ Brand data tools module loaded")
        
        # Check tools exist
        brand_tools = brand_module.BRAND_DATA_TOOLS
        print(f"  - Found {len(brand_tools)} Brand.dev tools:")
        for tool in brand_tools:
            print(f"    • {tool.name}")
            
    except Exception as e:
        print(f"✗ Failed to load Brand Data Tools: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "="*60)
    print("All imports successful! ✓")
    print("="*60 + "\n")
    
    print("Tool Details:")
    print("\nFal.ai Generation Tools (3 separate files):")
    print("  1. fal_text_to_image_tool.py → generate_image_text_to_image")
    print("     - Create images from text prompts")
    print("  2. fal_img_to_img_tool.py → generate_image_img_to_img")
    print("     - Transform images based on prompts")
    print("  3. fal_remove_bg_tool.py → remove_background_from_image")
    print("     - Remove backgrounds to create transparent PNGs")
    
    print("\nBrand.dev Data Tools:")
    print("  1. get_brand_data - Get brand assets (logos, colors, fonts)")
    print("  2. ai_query_brand_website - Extract custom data using AI queries")
    
    print("\nNext steps:")
    print("1. Add FAL_API_KEY to your .env file")
    print("2. Add BRAND_DEV_API_KEY to your .env file")
    print("3. Tools will be automatically loaded by load_all_tools()")
    print("4. Tools are now available to the LangGraph agent\n")
    
    return True


if __name__ == "__main__":
    success = test_imports()
    sys.exit(0 if success else 1)
