from e2b import Sandbox
from dotenv import load_dotenv

load_dotenv()

def find_player():
    print("🚀 Finding Player Ship...")
    sbx = Sandbox.create(template="game-gen-pre-v1")
    try:
        # Search recursively in assets for "playerShip1_blue"
        cmd = sbx.commands.run("find assets -name 'playerShip1_blue.png'")
        if cmd.exit_code == 0 and cmd.stdout.strip():
            print("✅ FOUND IT:", cmd.stdout.strip())
        else:
            print("❌ Not found. Listing first 20 PNGs to check structure:")
            ls = sbx.commands.run("find assets -name '*.png' | head -n 20")
            print(ls.stdout)
    finally:
        sbx.kill()

if __name__ == "__main__":
    find_player()
