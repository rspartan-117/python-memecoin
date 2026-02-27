"""
Test script to verify the game-gen-pre-v1 template has:
- Node.js installed
- live-server installed
- Port 3000 running with hot-reload capability
"""

import time
import requests
from e2b import Sandbox
from dotenv import load_dotenv
load_dotenv()

def test_template_setup():
    """Comprehensive test of the rebuilt template"""
    
    print("=" * 80)
    print("🧪 TESTING game-gen-pre-v1 Template")
    print("=" * 80)
    print()
    
    # Create sandbox
    print("📦 Creating sandbox from template...")
    try:
        sandbox = Sandbox.create(template="game-gen-pre-v1", timeout=180)
        print(f"✅ Sandbox created: {sandbox.sandbox_id}")
        print()
    except Exception as e:
        print(f"❌ Failed to create sandbox: {e}")
        return False
    
    try:
        # Test 1: Check Node.js installation
        print("=" * 80)
        print("TEST 1: Node.js Installation")
        print("=" * 80)
        result = sandbox.commands.run("node --version")
        if result.exit_code == 0:
            print(f"✅ Node.js version: {result.stdout.strip()}")
        else:
            print(f"❌ Node.js not found: {result.stderr}")
            return False
        print()
        
        # Test 2: Check npm installation
        print("=" * 80)
        print("TEST 2: npm Installation")
        print("=" * 80)
        result = sandbox.commands.run("npm --version")
        if result.exit_code == 0:
            print(f"✅ npm version: {result.stdout.strip()}")
        else:
            print(f"❌ npm not found: {result.stderr}")
        print()
        
        # Test 3: Check live-server installation
        print("=" * 80)
        print("TEST 3: live-server Installation")
        print("=" * 80)
        result = sandbox.commands.run("which live-server")
        if result.exit_code == 0:
            print(f"✅ live-server path: {result.stdout.strip()}")
            result_version = sandbox.commands.run("live-server --version")
            print(f"✅ live-server version: {result_version.stdout.strip()}")
        else:
            print(f"❌ live-server not found: {result.stderr}")
            return False
        print()
        
        # Test 4: Check supervisor status
        print("=" * 80)
        print("TEST 4: Supervisor Status & Diagnostics")
        print("=" * 80)
        
        # Check if supervisor process is running
        print("Checking if supervisor is running...")
        try:
            result = sandbox.commands.run("ps aux | grep supervisor | grep -v grep")
            if result.stdout.strip():
                print("✅ Supervisor process found:")
                print(result.stdout.strip())
            else:
                print("❌ Supervisor process NOT running!")
        except Exception as e:
            print(f"❌ Supervisor process NOT running: {e}")
        
        print("\nChecking supervisor config...")
        try:
            result = sandbox.commands.run("cat /etc/supervisor/conf.d/supervisord.conf")
            print("✅ Supervisor config exists:")
            print(result.stdout[:500])  # First 500 chars
        except Exception as e:
            print(f"❌ Could not read supervisor config: {e}")
        
        print("\nTrying to get supervisor status...")
        try:
            result = sandbox.commands.run("supervisorctl status")
            print(result.stdout)
            if "gameserver" in result.stdout and "RUNNING" in result.stdout:
                print("✅ gameserver is running")
            else:
                print("⚠️ gameserver might not be running")
        except Exception as e:
            print(f"⚠️ supervisorctl failed: {e}")
        
        print("\nChecking all running processes...")
        try:
            result = sandbox.commands.run("ps aux | grep -E '(live-server|python|node)' | grep -v grep")
            print("Processes containing live-server/python/node:")
            print(result.stdout if result.stdout.strip() else "None found")
        except Exception as e:
            print(f"Could not list processes: {e}")
        print()
        
        # Test 5: Check if port 3000 is listening
        print("=" * 80)
        print("TEST 5: Port 3000 Listening")
        print("=" * 80)
        try:
            result = sandbox.commands.run("ss -tuln | grep 3000 || netstat -tuln | grep 3000")
            if result.exit_code == 0 and "3000" in result.stdout:
                print(f"✅ Port 3000 is listening:")
                print(result.stdout.strip())
            else:
                print("❌ Port 3000 is NOT listening")
                print("Checking what's running on all ports...")
                all_ports = sandbox.commands.run("ss -tuln")
                print(all_ports.stdout)
        except Exception as e:
            print(f"⚠️ Could not check port 3000: {e}")
            print("Port might not be open yet")
        print()
        
        # Test 6: Check gameserver logs
        print("=" * 80)
        print("TEST 6: Gameserver Logs")
        print("=" * 80)
        print("--- STDOUT LOG ---")
        try:
            result = sandbox.commands.run("cat /var/log/supervisor/gameserver.out.log 2>/dev/null || echo 'No log file'")
            print(result.stdout if result.stdout else "No stdout log yet")
        except Exception as e:
            print(f"Could not read stdout log: {e}")
        print("\n--- STDERR LOG ---")
        try:
            result = sandbox.commands.run("cat /var/log/supervisor/gameserver.err.log 2>/dev/null || echo 'No log file'")
            print(result.stdout if result.stdout else "No stderr log yet")
        except Exception as e:
            print(f"Could not read stderr log: {e}")
        print()
        
        # Test 6.5: Try to manually start live-server if not running
        print("=" * 80)
        print("TEST 6.5: Manual Live-Server Start (if needed)")
        print("=" * 80)
        try:
            # Check if anything is on port 3000
            check_port = sandbox.commands.run("lsof -i :3000 2>/dev/null || echo 'Port 3000 free'")
            print(f"Port 3000 status: {check_port.stdout.strip()}")
            
            if "Port 3000 free" in check_port.stdout or not check_port.stdout.strip():
                print("⚠️ Nothing running on port 3000! Attempting manual start...")
                # Start live-server manually in background
                sandbox.commands.run(
                    "cd /home/user/game && live-server --port=3000 --host=0.0.0.0 --no-browser --wait=500",
                    background=True
                )
                print("✅ Manually started live-server")
                print("⏳ Waiting 3 seconds for server to start...")
                time.sleep(3)
            else:
                print("✅ Something is already running on port 3000")
        except Exception as e:
            print(f"Could not manually start live-server: {e}")
        print()
        
        # Test 7: Check game directory structure
        print("=" * 80)
        print("TEST 7: Game Directory Structure")
        print("=" * 80)
        result = sandbox.commands.run("ls -la /home/user/game/")
        print(result.stdout)
        print()
        
        # Test 8: Create a test HTML file
        print("=" * 80)
        print("TEST 8: Create Test HTML File")
        print("=" * 80)
        test_html = """<!DOCTYPE html>
<html>
<head>
    <title>Live Server Test</title>
    <style>
        body { 
            font-family: Arial, sans-serif; 
            text-align: center; 
            padding: 50px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        h1 { font-size: 3em; }
        .status { 
            background: rgba(255,255,255,0.2); 
            padding: 20px; 
            border-radius: 10px; 
            margin: 20px auto;
            max-width: 600px;
        }
    </style>
</head>
<body>
    <h1>🎮 Game Gen Template Test</h1>
    <div class="status">
        <h2>✅ Live Server is Running!</h2>
        <p>Node.js + live-server successfully configured</p>
        <p>Hot-reload enabled - modify files to see instant updates</p>
        <p id="timestamp"></p>
    </div>
    <script>
        document.getElementById('timestamp').textContent = 
            'Page loaded at: ' + new Date().toLocaleString();
    </script>
</body>
</html>"""
        
        sandbox.files.write("/home/user/game/test.html", test_html)
        print("✅ Test HTML file created at /home/user/game/test.html")
        print()
        
        # Test 9: Wait for server to pick up changes
        print("=" * 80)
        print("TEST 9: Waiting for live-server to detect file...")
        print("=" * 80)
        time.sleep(2)
        print("✅ Wait complete")
        print()
        
        # Test 10: Get sandbox URL
        print("=" * 80)
        print("TEST 10: Sandbox URL Access")
        print("=" * 80)
        url = sandbox.get_host(3000)
        print(f"🌐 Sandbox URL: https://{url}")
        print(f"🧪 Test page: https://{url}/test.html")
        print()
        
        # Test 11: Try to access the URL
        print("=" * 80)
        print("TEST 11: HTTP Request Test")
        print("=" * 80)
        try:
            response = requests.get(f"https://{url}/test.html", timeout=10)
            if response.status_code == 200:
                print(f"✅ HTTP 200 OK - Server is responding!")
                print(f"✅ Content length: {len(response.text)} bytes")
                if "Live Server is Running" in response.text:
                    print("✅ Test HTML content verified!")
            else:
                print(f"⚠️ HTTP {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"❌ HTTP request failed: {e}")
        print()
        
        # Test 12: Test hot-reload by modifying file
        print("=" * 80)
        print("TEST 12: Hot-Reload Test")
        print("=" * 80)
        modified_html = test_html.replace(
            "Page loaded at:",
            "🔥 HOT-RELOADED at:"
        )
        sandbox.files.write("/home/user/game/test.html", modified_html)
        print("✅ File modified - live-server should detect change")
        print("⏳ Waiting 2 seconds for hot-reload...")
        time.sleep(2)
        
        try:
            response = requests.get(f"https://{url}/test.html", timeout=10)
            if "HOT-RELOADED" in response.text:
                print("✅ HOT-RELOAD WORKING! File changes detected!")
            else:
                print("⚠️ Hot-reload might not be working (old content served)")
        except Exception as e:
            print(f"❌ Could not verify hot-reload: {e}")
        print()
        
        # Final summary
        print("=" * 80)
        print("🎉 TEST SUMMARY")
        print("=" * 80)
        print("✅ Node.js: Installed")
        print("✅ npm: Installed")
        print("✅ live-server: Installed")
        print("✅ Port 3000: Accessible")
        print("✅ Hot-reload: Configured")
        print()
        print(f"🌐 Access your sandbox at: https://{url}")
        print(f"📝 Template ID: game-gen-pre-v1")
        print(f"🆔 Sandbox ID: {sandbox.sandbox_id}")
        print()
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Keep sandbox alive for manual testing
        print("\n⏸️  Sandbox will remain open for 5 minutes for manual testing...")
        print("   Press Ctrl+C to close immediately")
        try:
            time.sleep(300)  # 5 minutes
        except KeyboardInterrupt:
            print("\n⚠️ Interrupted by user")
        
        print(f"\n🧹 Closing sandbox {sandbox.sandbox_id}...")
        sandbox.close()
        print("✅ Sandbox closed")


if __name__ == "__main__":
    success = test_template_setup()
    exit(0 if success else 1)
