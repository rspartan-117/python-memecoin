import time
from e2b_code_interpreter import Sandbox
from dotenv import load_dotenv

load_dotenv()

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Simple Kaplay Game</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #05050a;
            overflow: hidden;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        canvas {
            border: 2px solid #333;
            box-shadow: 0 0 20px rgba(100, 200, 255, 0.4);
        }
    </style>
</head>
<body>
    <!-- Kaplay in global mode -->
    <script src="https://unpkg.com/kaplay@3001.0.19/dist/kaplay.js"></script>
    <script src="game.js"></script>
</body>
</html>
"""

GAME_JS = """
// Kaplay in global mode (no import)
kaplay({
    width: 800,
    height: 600,
    global: true,
    background: [20, 20, 40],
});

// Use a verified asset:
// From your listing: assets/2d/pixel_platformer/Tiles/tile_0000.png
loadSprite("player", "assets/2d/pixel_platformer/Tiles/tile_0000.png");

scene("game", () => {
    let score = 0;

    // Player using sprite
    const player = add([
        sprite("player"),
        pos(width() / 2, height() - 80),
        anchor("center"),
        area(),
        scale(2),         // make tile bigger
        "player",
    ]);

    // Move left/right
    onKeyDown("left", () => {
        player.move(-300, 0);
        if (player.pos.x < 20) player.pos.x = 20;
    });

    onKeyDown("right", () => {
        player.move(300, 0);
        if (player.pos.x > width() - 20) player.pos.x = width() - 20;
    });

    // Shoot bullets (simple yellow rects)
    onKeyPress("space", () => {
        add([
            rect(4, 16),
            pos(player.pos.x, player.pos.y - 25),
            color(255, 255, 100),
            anchor("center"),
            area(),
            move(UP, 500),
            "bullet",
        ]);
    });

    // Spawn falling enemies (red squares)
    loop(1.2, () => {
        add([
            rect(30, 30),
            pos(rand(30, width() - 30), -40),
            color(255, 80, 80),
            anchor("center"),
            area(),
            move(DOWN, rand(150, 250)),
            "enemy",
        ]);
    });

    // Bullet hits enemy
    onCollide("bullet", "enemy", (b, e) => {
        destroy(b);
        destroy(e);
        shake(4);
        score += 10;
        scoreLabel.text = "SCORE: " + score;
    });

    // Enemy hits player -> instant game over
    onCollide("player", "enemy", (p, e) => {
        destroy(e);
        shake(12);
        go("gameover", score);
    });

    // Cleanup off-screen
    onUpdate("bullet", (b) => {
        if (b.pos.y < -50) destroy(b);
    });

    onUpdate("enemy", (e) => {
        if (e.pos.y > height() + 50) destroy(e);
    });

    // UI
    const scoreLabel = add([
        text("SCORE: 0"),
        pos(20, 20),
        color(255, 255, 255),
    ]);

    add([
        text("← → move   space shoot"),
        pos(width() / 2, height() - 30),
        anchor("center"),
        color(180, 180, 180),
    ]);
});

scene("gameover", (finalScore) => {
    add([
        text("GAME OVER"),
        pos(width() / 2, height() / 2 - 40),
        anchor("center"),
        scale(2),
        color(255, 100, 100),
    ]);

    add([
        text("SCORE: " + finalScore),
        pos(width() / 2, height() / 2 + 10),
        anchor("center"),
        color(255, 255, 255),
    ]);

    add([
        text("Press SPACE to restart"),
        pos(width() / 2, height() / 2 + 50),
        anchor("center"),
        color(200, 200, 200),
    ]);

    onKeyPress("space", () => go("game"));
});

go("game");
"""

def main():
    print("🚀 Starting SIMPLE ASSET GAME test...")

    sbx = Sandbox.create(template="game-gen-pre-v1")

    try:
        # Ensure we’re in /home/user/game
        pwd = sbx.commands.run("pwd")
        print("Current dir in sandbox:", pwd.stdout.strip())

        # Write index.html and game.js to the game root
        sbx.files.write("/home/user/game/index.html", INDEX_HTML)
        sbx.files.write("/home/user/game/game.js", GAME_JS)
        print("✅ Wrote index.html and game.js")

        # Quick sanity check
        ls = sbx.commands.run("ls -lh /home/user/game")
        print("\nFiles in /home/user/game:\n", ls.stdout)

        # Get URL
        host = sbx.get_host(3000)
        url = f"https://{host}"
        print("\n🎮 Open this URL in your browser:")
        print(url)
        print("\nControls: ← → to move, SPACE to shoot")

        print("\n⏳ Keeping sandbox alive for 5 minutes...")
        time.sleep(300)

    finally:
        sbx.kill()
        print("✅ Sandbox closed")

if __name__ == "__main__":
    main()
