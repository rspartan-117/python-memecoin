import os
from e2b_code_interpreter import Sandbox
from dotenv import load_dotenv

# Load your E2B_API_KEY
load_dotenv()

def list_all_assets():
    print("🚀 Connecting to Sandbox to inspect assets...")
    sbx = Sandbox.create(template="game-gen-pre-v1")
    
    try:
        print("\n📂 Scanning asset directory structure...\n")
        
        # List all files in assets folder recursively (depth 4 to see nested folders)
        files = sbx.files.list("/home/user/game/assets", depth=4)
        
        # Organize by category
        assets_2d = []
        assets_3d = []
        dirs_2d = set()
        dirs_3d = set()
        
        for file in files:
            # Clean path for display
            clean_path = file.path.replace("/home/user/game/", "")
            
            # Check if it's a directory (type == 'dir')
            if file.type == 'dir':
                if "2d" in file.path:
                    dirs_2d.add(clean_path)
                elif "3d" in file.path:
                    dirs_3d.add(clean_path)
            else:
                # It's a file
                if "2d" in file.path:
                    assets_2d.append(clean_path)
                elif "3d" in file.path:
                    assets_3d.append(clean_path)
        
        # Print results
        print("=" * 70)
        print("2D ASSETS (Sample - First 30 files)")
        print("=" * 70)
        for asset in sorted(assets_2d):
            print(asset)
        
        print(f"\n... Total 2D files: {len(assets_2d)}")
        
        print("\n" + "=" * 70)
        print("3D ASSETS (Sample - First 30 files)")
        print("=" * 70)
        for asset in sorted(assets_3d):
            print(asset)
        
        print(f"\n... Total 3D files: {len(assets_3d)}")
        
        # Print pack structure
        print("\n" + "=" * 70)
        print("PACK STRUCTURE (Folders)")
        print("=" * 70)
        
        print("\n2D Packs:")
        for d in sorted(dirs_2d)[:20]:  # Limit to first 20 folders
            print(f"  - {d}")
        
        print("\n3D Packs:")
        for d in sorted(dirs_3d)[:20]:  # Limit to first 20 folders
            print(f"  - {d}")
        
        print("\n" + "=" * 70)
        print("✅ Copy the output above and paste it back to me!")
        print("=" * 70)

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        sbx.kill()

if __name__ == "__main__":
    list_all_assets()
