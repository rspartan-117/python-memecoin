import time
from e2b import Sandbox
from dotenv import load_dotenv
load_dotenv()
# 1. Define your game files
html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>E2B Clicker Game</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="container">
        <h1>Score: <span id="score">0</span></h1>
        <button id="clickBtn">Click Me!</button>
    </div>
    <script src="script.js"></script>
</body>
</html>
"""

css_content = """
body { font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #f0f0f0; }
.container { text-align: center; padding: 2rem; background: white; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
button { padding: 10px 20px; font-size: 1.2rem; cursor: pointer; background: #007bff; color: white; border: none; border-radius: 5px; }
button:hover { background: #0056b3; }
"""

js_content = """
let score = 0;
const scoreEl = document.getElementById('score');
document.getElementById('clickBtn').addEventListener('click', () => {
    score++;
    scoreEl.textContent = score;
});
"""

def main():
    print("🚀 Creating sandbox...")
    # 2. Create the sandbox
    with Sandbox.create(template="react-fast-mongo-pre-v0",timeout=1000) as sandbox:
        print("📂 Writing game files...")
        # Write files to the sandbox filesystem
        sandbox.files.write("index.html", html_content)
        sandbox.files.write("style.css", css_content)
        sandbox.files.write("script.js", js_content)

        print("🌐 Starting web server...")
        # 3. Start python http.server in the background on port 3000
        # We use background=True so the script doesn't block here
        sandbox.commands.run("python -m http.server 3000", background=True)

        # 4. Get the public URL
        # E2B automatically creates a public URL for open ports
        url = sandbox.get_host(3000)
        public_url = f"https://{url}"

        print(f"\n✅ Game is live at: {public_url}")
        print("Press Ctrl+C to stop the sandbox")

        try:
            # Keep script alive so the sandbox stays active
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Stopping sandbox...")

if __name__ == "__main__":
    main()
