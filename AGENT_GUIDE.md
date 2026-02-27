# Agent Guide: meme-coin-base-v0 Sandbox Environment

> **Purpose**: This document explains the sandbox internal structure and error logging system for AI agents building landing pages.

## 🎯 Quick Start for Agents

You are working in an E2B sandbox with automatic client-side error logging. Your workflow:

```python
from e2b import Sandbox
import time

sandbox = Sandbox.create("meme-coin-base-v0")

# 1. Write your HTML
sandbox.files.write("/home/user/project/index.html", html_content)

# 2. Wait for browser to load and execute JavaScript
time.sleep(5)

# 3. Check for errors
errors = sandbox.files.read("/var/log/supervisor/client_errors.log")

# 4. Parse and fix errors, repeat if needed
```

**That's it!** No API calls needed - just read the log file.

---

## 📁 Sandbox File Structure

```
/home/user/project/          # Your working directory
├── index.html               # Landing page (you create/modify this)
├── style.css                # Styles (optional, can inline in HTML)
├── script.js                # !IMPORTANT: Pre-installed error logger
├── background.webp          # Default background image
└── fonts/                   # Custom fonts (Cuba, Tomato Grotesk)

/var/log/supervisor/         # Log files (read-only for you)
├── client_errors.log        # ⭐ JavaScript errors from browser
├── client_events.log        # Page load events
├── error_logger.out.log     # Error service logs
├── error_logger.err.log     # Error service errors
├── webserver.out.log        # Web server logs
├── webserver.err.log        # Web server errors
├── control_api.out.log      # API service logs
└── control_api.err.log      # API service errors
```

### Critical Files

| File | Purpose | Agent Action |
|------|---------|--------------|
| `/home/user/project/index.html` | Landing page HTML | **Write your generated code here** |
| `/home/user/project/script.js` | Error logging script | **MUST include in HTML** with `<script src="script.js"></script>` |
| `/var/log/supervisor/client_errors.log` | Browser JavaScript errors | **Read to detect errors** |
| `/var/log/supervisor/client_events.log` | Page load confirmations | **Read to verify page loaded** |

---

## 🔧 Sandbox Services Architecture

The sandbox runs 3 services managed by **supervisor**:

### 1. Webserver (Port 3000)
- **Service**: `live-server` with auto-reload
- **Purpose**: Serves your HTML/CSS/JS files
- **Features**: 
  - Hot reload on file changes
  - CORS enabled
  - Instant browser refresh when you write files
- **Access**: `https://{sandbox.get_host(3000)}`

### 2. Control API (Port 8000)
- **Service**: FastAPI server
- **Purpose**: File operations (optional - you can use `sandbox.files` instead)
- **Endpoints**:
  - `GET /status` - Health check
  - `GET /health` - Service status
- **Access**: `https://{sandbox.get_host(8000)}`
- **Note**: File operations removed - use `sandbox.files.write()` instead

### 3. Error Logger (Port 9000)
- **Service**: Minimal HTTP server (`error_logger.py`)
- **Purpose**: Receives errors from browser, writes to log files
- **Features**:
  - Accepts POST requests from `script.js`
  - Appends JSON to log files
  - CORS enabled
  - Runs silently in background
- **Access**: Browser posts to `https://9000-{sandbox-id}.e2b.app`
- **Note**: You don't interact with this directly

---

## 🪵 Error Logging System

### How It Works

```
1. Browser loads your HTML
   ↓
2. script.js captures any JavaScript error
   ↓
3. script.js POSTS error to port 9000
   ↓
4. error_logger.py receives POST
   ↓
5. error_logger appends JSON line to /var/log/supervisor/client_errors.log
   ↓
6. You read the file with sandbox.files.read()
```

### Error Log Format

Each line in `/var/log/supervisor/client_errors.log` is a JSON object:

```json
{
  "ts": "2026-02-25T12:04:17.026219",
  "data": {
    "type": "error",
    "message": "Uncaught ReferenceError: x is not defined",
    "source": "https://3000-sandbox.e2b.app/",
    "line": 45,
    "column": 21,
    "stack": "ReferenceError: x is not defined\n    at ...",
    "timestamp": "2026-02-25T12:04:17.083Z",
    "url": "https://3000-sandbox.e2b.app/"
  }
}
```

### Error Types Captured

| Type | Description | Example |
|------|-------------|---------|
| `error` | Runtime JavaScript errors | `ReferenceError`, `TypeError`, `SyntaxError` |
| `unhandledRejection` | Promise rejections | `fetch()` failures, async errors |
| `pageLoad` | Successful page load | Logged to `client_events.log` |

---

## 🤖 Agent Implementation Patterns

### Pattern 1: Basic Error Detection

```python
def check_for_errors(sandbox):
    """Check if generated HTML has JavaScript errors"""
    try:
        raw = sandbox.files.read("/var/log/supervisor/client_errors.log")
        if not raw.strip():
            return []
        
        errors = []
        for line in raw.strip().splitlines():
            if line:
                import json
                errors.append(json.loads(line))
        return errors
    except:
        return []

# Usage
sandbox.files.write("/home/user/project/index.html", html)
time.sleep(5)  # Wait for browser to load
errors = check_for_errors(sandbox)

if errors:
    print(f"Found {len(errors)} errors - need to fix")
else:
    print("No errors - page is clean!")
```

### Pattern 2: Iterative Error Fixing Loop

```python
def fix_errors_iteratively(sandbox, generate_html_fn, max_iterations=5):
    """Keep fixing until no errors or max iterations reached"""
    
    for iteration in range(max_iterations):
        print(f"Iteration {iteration + 1}")
        
        # Clear old errors from previous iteration
        sandbox.files.write("/var/log/supervisor/client_errors.log", "")
        
        # Generate/regenerate HTML
        html = generate_html_fn()
        sandbox.files.write("/home/user/project/index.html", html)
        
        # Wait for live-server reload + JS execution
        time.sleep(5)
        
        # Check for errors
        errors = check_for_errors(sandbox)
        
        if not errors:
            print("✅ Success - no errors!")
            return True
        
        print(f"❌ Found {len(errors)} errors:")
        for e in errors:
            print(f"  - {e['data']['message']}")
        
        # Pass errors to LLM for next iteration
        # generate_html_fn should use this context
    
    print("⚠️  Max iterations reached")
    return False
```

### Pattern 3: Error-Aware HTML Generation

```python
def generate_html_with_error_context(sandbox, prompt, previous_errors=None):
    """Generate HTML, incorporating error feedback if available"""
    
    if previous_errors:
        error_context = "\n".join([
            f"- Line {e['data']['line']}: {e['data']['message']}"
            for e in previous_errors
        ])
        prompt += f"\n\nFix these errors:\n{error_context}"
    
    # Call your LLM
    html = llm.generate(prompt)
    
    # Ensure script.js is included for error logging
    if '<script src="script.js"></script>' not in html:
        # Inject before </body>
        html = html.replace('</body>', 
            '<script src="script.js"></script>\n</body>')
    
    return html
```

---

## ⚠️ Common Pitfalls for Agents

### 1. Forgetting to Include script.js

**❌ Wrong:**
```html
<!DOCTYPE html>
<html>
<body>
    <h1>My Page</h1>
</body>
</html>
```

**✅ Correct:**
```html
<!DOCTYPE html>
<html>
<body>
    <h1>My Page</h1>
    <script src="script.js"></script>
</body>
</html>
```

### 2. Not Waiting After Writing Files

**❌ Wrong:**
```python
sandbox.files.write("/home/user/project/index.html", html)
errors = check_for_errors(sandbox)  # Too fast!
```

**✅ Correct:**
```python
sandbox.files.write("/home/user/project/index.html", html)
time.sleep(5)  # Wait for live-server reload + JS execution
errors = check_for_errors(sandbox)
```

### 3. Not Clearing Logs Between Iterations

**❌ Wrong:**
```python
for i in range(3):
    sandbox.files.write("/home/user/project/index.html", html_v1)
    time.sleep(5)
    errors = check_for_errors(sandbox)  # Contains OLD errors too!
```

**✅ Correct:**
```python
for i in range(3):
    sandbox.files.write("/var/log/supervisor/client_errors.log", "")  # Clear!
    sandbox.files.write("/home/user/project/index.html", html_v1)
    time.sleep(5)
    errors = check_for_errors(sandbox)  # Only NEW errors
```

### 4. Checking Logs Before Browser Executes

The sequence matters:
1. You write HTML → file saved
2. live-server detects change → reloads browser (~1s)
3. Browser parses HTML → executes JavaScript (~1-2s)
4. Errors occur → script.js catches them (~0.5s)
5. script.js POSTs to error_logger (~0.5s)
6. error_logger writes to file (~0.1s)

**Total: ~3-4 seconds minimum**

Always wait at least 5 seconds to be safe.

---

## 🎨 Working with Assets

### Background Images

Default background is at `/home/user/project/background.webp`. Use in CSS:

```css
body {
    background-image: url('background.webp');
    background-size: cover;
}
```

### Custom Fonts

Pre-installed fonts are in `/home/user/project/fonts/`:
- `Cuba-Regular.woff2`
- `TomatoGrotesk-Regular.woff2`

Use in CSS:
```css
@font-face {
    font-family: 'Cuba';
    src: url('fonts/Cuba-Regular.woff2') format('woff2');
}

body {
    font-family: 'Cuba', sans-serif;
}
```

### Adding New Assets

Upload via `sandbox.files.write()`:

```python
# Upload image
with open("local_logo.png", "rb") as f:
    sandbox.files.write("/home/user/project/logo.png", f.read())

# Use in HTML
html = '<img src="logo.png" alt="Logo">'
```

---

## 🔍 Debugging Tips

### Check Service Status

```python
status = sandbox.commands.run("sudo supervisorctl status")
print(status.stdout)
# Should show all 3 services RUNNING
```

### Check Service Logs

```python
# Error logger service logs
log = sandbox.files.read("/var/log/supervisor/error_logger.out.log")
print(log)

# Webserver logs
log = sandbox.files.read("/var/log/supervisor/webserver.out.log")
print(log)
```

### Verify script.js Exists

```python
check = sandbox.commands.run("ls -la /home/user/project/script.js")
if "script.js" in check.stdout:
    print("✅ script.js present")
else:
    print("❌ script.js missing!")
```

### Check Page Load Events

```python
events = sandbox.files.read("/var/log/supervisor/client_events.log")
print(events)
# Should show pageLoad events if browser loaded successfully
```

---

## 📊 Success Metrics for Agents

Your landing page is **production-ready** when:

✅ **No JavaScript errors** in `client_errors.log`  
✅ **Page load event** appears in `client_events.log`  
✅ **HTML is valid** (proper doctype, structured tags)  
✅ **Mobile responsive** (viewport meta tag present)  
✅ **Fast load** (minimal external dependencies)  
✅ **Visual appeal** (gradients, animations, modern design)

---

## 🚀 Example: Complete Agent Workflow

```python
from e2b import Sandbox
import time
import json

def agent_build_landing_page(prompt):
    """Complete workflow: create sandbox → generate → fix errors → verify"""
    
    # 1. Create sandbox
    sandbox = Sandbox.create("meme-coin-base-v0", timeout=600)
    url = f"https://{sandbox.get_host(3000)}"
    print(f"🌐 Landing page: {url}")
    
    # Wait for services
    time.sleep(8)
    
    # 2. Generate initial HTML
    html = generate_html(prompt)  # Your LLM call
    
    # 3. Iterative fixing loop
    for iteration in range(3):
        print(f"\n🔄 Iteration {iteration + 1}")
        
        # Clear previous errors
        sandbox.files.write("/var/log/supervisor/client_errors.log", "")
        
        # Write HTML
        sandbox.files.write("/home/user/project/index.html", html)
        
        # Wait for execution
        time.sleep(5)
        
        # Check errors
        errors_raw = sandbox.files.read("/var/log/supervisor/client_errors.log")
        
        if not errors_raw.strip():
            print("✅ No errors - page is ready!")
            
            # Verify page loaded
            events = sandbox.files.read("/var/log/supervisor/client_events.log")
            if "pageLoad" in events:
                print("✅ Page load confirmed")
            
            return url, sandbox
        
        # Parse errors
        errors = [json.loads(line) for line in errors_raw.strip().splitlines()]
        print(f"❌ Found {len(errors)} errors")
        
        # Generate fix
        error_details = "\n".join([
            f"Line {e['data']['line']}: {e['data']['message']}"
            for e in errors
        ])
        html = generate_html(prompt + f"\n\nFix these errors:\n{error_details}")
    
    print("⚠️  Could not eliminate all errors in 3 iterations")
    return url, sandbox

# Usage
url, sandbox = agent_build_landing_page("Create a meme coin landing page")
print(f"\n🎉 Done: {url}")

input("Press Enter to close...")
sandbox.kill()
```

---

## 💡 Best Practices for Agents

1. **Always include `<script src="script.js"></script>`** in HTML
2. **Wait 5+ seconds** after writing HTML before checking errors
3. **Clear logs** between iterations to avoid confusion
4. **Check both errors and events** logs for complete picture
5. **Use `try/except`** when parsing JSON logs (handle empty files)
6. **Set max iterations** (3-5) to avoid infinite loops
7. **Log your progress** for debugging
8. **Verify services are running** if errors aren't being captured
9. **Keep HTML self-contained** (inline CSS/JS when possible)
10. **Test the final URL** before marking as complete

---

## 🔐 Security Notes

- Sandbox is **isolated** - no access to external network by default
- All services run with **appropriate permissions**
- Logs are **read-only** for the error_logger service
- **CORS enabled** for browser-to-service communication

---

## 📖 Additional Resources

- [AGENT_USAGE.md](AGENT_USAGE.md) - Detailed code examples and patterns
- [SANDBOX_STRUCTURE.md](SANDBOX_STRUCTURE.md) - Full logging architecture
- [AGENT_ERROR_ACCESS.md](AGENT_ERROR_ACCESS.md) - Error access examples

---

## ⚡ Quick Reference

| Task | Command |
|------|---------|
| Write HTML | `sandbox.files.write("/home/user/project/index.html", html)` |
| Read errors | `sandbox.files.read("/var/log/supervisor/client_errors.log")` |
| Clear errors | `sandbox.files.write("/var/log/supervisor/client_errors.log", "")` |
| Check events | `sandbox.files.read("/var/log/supervisor/client_events.log")` |
| Get URL | `f"https://{sandbox.get_host(3000)}"` |
| Check services | `sandbox.commands.run("sudo supervisorctl status")` |

---

**Remember**: The sandbox is designed to make error detection effortless. Just write HTML, wait, and read the log file. No complex APIs, no special tools - just files. 🎯
