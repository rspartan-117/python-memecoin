import os
from e2b_code_interpreter import Sandbox
from dotenv import load_dotenv

load_dotenv()

OUTPUT_FILE = "assets_list.txt"

def list_all_assets():
    print("🚀 Connecting to Sandbox to inspect assets...")
    sbx = Sandbox.create(template="game-gen-pre-v1")
    
    try:
        print(f"\n📂 Scanning assets (Depth: 5)... Output will be saved to '{OUTPUT_FILE}'\n")
        
        # List all files recursively
        files = sbx.files.list("/home/user/game/assets", depth=5)
        
        # Data Containers
        assets_2d = []
        assets_3d = []
        glb_files = []
        dirs_2d = set()
        dirs_3d = set()
        
        # Process Files
        for file in files:
            clean_path = file.path.replace("/home/user/game/", "")
            
            if file.type == 'dir':
                if "2d" in file.path: dirs_2d.add(clean_path)
                elif "3d" in file.path: dirs_3d.add(clean_path)
            else:
                if "2d" in file.path: assets_2d.append(clean_path)
                elif "3d" in file.path: 
                    assets_3d.append(clean_path)
                    if file.name.lower().endswith('.glb'):
                        glb_files.append(clean_path)

        # Write to File
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(" 3D GLB MODELS (Ready for Game Use)\n")
            f.write("=" * 80 + "\n")
            if glb_files:
                for glb in sorted(glb_files):
                    f.write(f"{glb}\n")
            else:
                f.write("No .glb files found.\n")
            f.write(f"\nTotal GLB files: {len(glb_files)}\n\n")

            f.write("=" * 80 + "\n")
            f.write(" 2D ASSETS (All Files)\n")
            f.write("=" * 80 + "\n")
            for asset in sorted(assets_2d):
                f.write(f"{asset}\n")
            f.write(f"\nTotal 2D files: {len(assets_2d)}\n\n")

            f.write("=" * 80 + "\n")
            f.write(" 3D ASSETS (All Files)\n")
            f.write("=" * 80 + "\n")
            for asset in sorted(assets_3d):
                f.write(f"{asset}\n")
            f.write(f"\nTotal 3D files: {len(assets_3d)}\n\n")
            
            f.write("=" * 80 + "\n")
            f.write(" DIRECTORY STRUCTURE\n")
            f.write("=" * 80 + "\n")
            f.write("2D Packs:\n")
            for d in sorted(dirs_2d): f.write(f"  - {d}\n")
            f.write("\n3D Packs:\n")
            for d in sorted(dirs_3d): f.write(f"  - {d}\n")

        print(f"✅ DONE! Asset list saved to: {os.path.abspath(OUTPUT_FILE)}")
        print(f"   Found {len(glb_files)} usable 3D models.")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        sbx.kill()

if __name__ == "__main__":
    list_all_assets()
