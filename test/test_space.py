import time
import shutil
import os
from e2b_code_interpreter import Sandbox
from dotenv import load_dotenv

load_dotenv()

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Space Shooter Final</title>
    <style>body { margin: 0; overflow: hidden; background: #000; }</style>
    <script src="https://unpkg.com/kaplay@3001.0.19/dist/kaplay.js"></script>
    <script src="game.js"></script>
</head>
<body></body>
</html>
"""

GAME_JS = """
kaplay({
    width: 800,
    height: 600,
    global: true,
    background: [10, 10, 20],
    debug: true,
});

// DEBUG: Log that we started
debug.log("Starting Game Init...");

// LOAD ASSETS (Now in root folder)
loadSprite("player", "player.png");
loadSprite("bullet", "bullet.png");
loadSprite("enemy", "player.png"); // Reuse player for enemy

// SCENE: Loading
scene("loading", () => {
    const label = add([
        text("Loading Assets...", { size: 24 }),
        pos(width()/2, height()/2),
        anchor("center"),
    ]);
    
    // Wait a moment to ensure assets are processed
    wait(1.0, () => {
        debug.log("Switching to game scene...");
        go("game");
    });
});

// SCENE: Game
scene("game", () => {
    debug.log("Game Scene Active");
    let score = 0;
    
    // UI
    const scoreLabel = add([
        text("Score: 0", { size: 24 }),
        pos(24, 24),
    ]);

    // Player
    const player = add([
        sprite("player"),
        pos(width() / 2, height() - 80),
        anchor("center"),
        area(),
        "player",
        scale(0.5)
    ]);

    // Controls
    onKeyDown("left", () => {
        player.move(-400, 0);
        if (player.pos.x < 30) player.pos.x = 30;
    });

    onKeyDown("right", () => {
        player.move(400, 0);
        if (player.pos.x > width() - 30) player.pos.x = width() - 30;
    });

    onKeyPress("space", () => {
        add([
            sprite("bullet"),
            pos(player.pos.x, player.pos.y - 40),
            anchor("center"),
            area(),
            move(UP, 600),
            "bullet",
        ]);
    });

    // Enemies
    loop(1.2, () => {
        add([
            sprite("enemy"),
            pos(rand(40, width() - 40), -50),
            anchor("center"),
            area(),
            move(DOWN, 200),
            "enemy",
            scale(0.5),
            rotate(180),
            color(255, 100, 100)
        ]);
    });

    // Collisions
    onCollide("bullet", "enemy", (b, e) => {
        destroy(b);
        destroy(e);
        shake(2);
        score += 100;
        scoreLabel.text = "Score: " + score;
    });

    onCollide("player", "enemy", (p, e) => {
        destroy(e);
        shake(20);
        go("gameover", score);
    });
});

scene("gameover", (score) => {
    add([
        text("GAME OVER\\nScore: " + score, { align: "center" }),
        pos(width() / 2, height() / 2),
        anchor("center"),
    ]);
    onKeyPress("space", () => go("game"));
});

// Start
go("loading");
"""

def main():
    print("🚀 Starting Bulletproof Space Shooter Build...")
    sbx = Sandbox.create(template="game-gen-pre-v1")

    try:
        # 1. Locate specific assets
        base_path = "/home/user/game/assets/2d/space_shooter/PNG/Sprites"
        
        # We'll just grab the first PNG in Ships and Missiles
        ships_files = sbx.files.list(f"{base_path}/Ships")
        missiles_files = sbx.files.list(f"{base_path}/Missiles")
        
        ship_file = next((f.name for f in ships_files if f.name.endswith(".png")), None)
        missile_file = next((f.name for f in missiles_files if f.name.endswith(".png")), None)

        if not ship_file or not missile_file:
            print("❌ Assets missing!")
            return

        print(f"✅ Found assets: {ship_file}, {missile_file}")
        
        # 2. COPY assets to root (/home/user/game/)
        # This fixes any weird path/symlink/permission issues for the web server
        print("📦 Copying assets to root for easy access...")
        
        # We use 'cp' command
        sbx.commands.run(f"cp '{base_path}/Ships/{ship_file}' /home/user/game/player.png")
        sbx.commands.run(f"cp '{base_path}/Missiles/{missile_file}' /home/user/game/bullet.png")
        
        # 3. Write Game Code
        sbx.files.write("/home/user/game/game.js", GAME_JS)
        sbx.files.write("/home/user/game/index.html", INDEX_HTML)

        # 4. Serve
        host = sbx.get_host(3000)
        print("\n" + "="*70)
        print(f"🎮 GAME READY: https://{host}")
        print("="*70)
        print("Assets are now at root (player.png, bullet.png).")
        print("If this is black, check Console F12 for network errors.")
        
        time.sleep(300)

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        sbx.kill()

if __name__ == "__main__":
    main()
