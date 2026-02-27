from e2b import Sandbox, AsyncSandbox
import asyncio
import inspect
import re
import logging
import time  # Add this import
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

_logger = logging.getLogger(__name__)


async def test_async():
    sandbox = await AsyncSandbox.create(
        template="react-fast-mongo-pre-v0", timeout=600, secure=True
    )
    print("\n" + "=" * 70)
    print("✅ SANDBOX CREATED - UPDATING CONFIGURATION : ", sandbox.sandbox_id)
    print("=" * 70)

    # Get the preview URLs
    frontend_url = f"https://{sandbox.get_host(3000)}"
    backend_url = f"https://{sandbox.get_host(8000)}"

    print(f"🌐 Frontend: {frontend_url}")
    print(f"🔧 Backend:  {backend_url}")
    print("=" * 70)

    # Step 1: Update frontend .env with backend URL
    print("📝 Updating frontend/.env with backend URL...")
    env_content = f"""REACT_APP_BACKEND_URL={backend_url}
DISABLE_HOT_RELOAD=false
REACT_APP_ENABLE_VISUAL_EDITS=false
ENABLE_HEALTH_CHECK=false
"""
    await sandbox.files.write("/home/user/code/frontend/.env", env_content)
    print("✅ Updated frontend/.env")
    return frontend_url, backend_url


if __name__ == "__main__":

    # asyncio.run(test_async())
    sandbox = Sandbox.create(
        template="react-fast-mongo-pre-v0", timeout=600, secure=True
    )

    print("\n" + "=" * 70)
    print("✅ SANDBOX CREATED - UPDATING CONFIGURATION : ", sandbox.sandbox_id)
    print("=" * 70)

    # Get the preview URLs
    frontend_url = f"https://{sandbox.get_host(3000)}"
    backend_url = f"https://{sandbox.get_host(8000)}"

    print(f"🌐 Frontend: {frontend_url}")
    print(f"🔧 Backend:  {backend_url}")
    print("=" * 70)

    # Step 1: Update frontend .env with backend URL
    print("📝 Updating frontend/.env with backend URL...")
    env_content = f"""REACT_APP_BACKEND_URL={backend_url}
DISABLE_HOT_RELOAD=false
REACT_APP_ENABLE_VISUAL_EDITS=false
ENABLE_HEALTH_CHECK=false
"""
    sandbox.files.write("/home/user/code/frontend/.env", env_content)
    print("✅ Updated frontend/.env")

    # Step 2: Restart frontend service to apply changes
    print("🔄 Restarting frontend service...")
    # result = sandbox.commands.run(
    #     "sudo supervisorctl restart frontend", background=True, timeout=2
    # )
    # print(f"   {result._stdout}")

    # # Step 3: Wait a moment for the service to restart
    # print("⏳ Waiting for frontend to restart...")
    # time.sleep(5)

    # # Step 4: Check service status
    # print("\n📊 Service Status:")
    # status = sandbox.commands.run(
    #     "sudo supervisorctl status", background=True, timeout=2
    # )
    # print(status._stdout)

    print("\n" + "=" * 70)
    print("✅ CONFIGURATION COMPLETE")
    print("=" * 70)
    print(f"🌐 Frontend: {frontend_url}")
    print(f"🔧 Backend:  {backend_url}")
    print(f"📄 Logs: /var/log/supervisor/")
    print("=" * 70)
    print("\n💡 Frontend now configured to connect to backend!")
    print("   Check browser console for connection status")
    print("=" * 70)

    # Keep sandbox alive
    input("\n⏸️  Press Enter to close sandbox...")
    sandbox.kill()
