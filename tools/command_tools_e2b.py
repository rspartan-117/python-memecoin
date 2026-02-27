"""
CommandTools for LangGraph - E2B Sandbox Command Operations
Migrated from Agno to LangChain tools

Features:
- ALL tools require RunnableConfig with user/project context
- Unified run_command tool - handles both foreground and background execution
- Simple command execution with timeout support
- Long-running service management (servers, React frontends, etc.)
- Process listing and killing
- Stdin streaming for interactive commands
- Automatic dependency file syncing
- All original methods retained (including commented tools)
"""

import asyncio
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass
from enum import Enum

from langchain.tools import tool, ToolRuntime

from context.runtime_context import RuntimeContext
from agent_state import LandingPageAgentState
from sandbox_manager import get_user_sandbox
from db.service import db_service

# =============================================================================
# TYPE DEFINITIONS AND ENUMS
# =============================================================================


class ProcessStatus(Enum):
    """Process execution status"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    KILLED = "killed"


class ServiceType(Enum):
    """Types of long-running services"""

    WEB_SERVER = "web_server"
    API_SERVER = "api_server"
    FRONTEND_DEV = "frontend_dev"  # React, Vue, Angular dev servers
    DATABASE = "database"
    BACKGROUND_TASK = "background_task"
    CUSTOM = "custom"


@dataclass
class ProcessInfo:
    """Information about a running process"""

    pid: int
    tag: str
    cmd: str
    args: List[str]
    envs: Dict[str, str]
    cwd: str

    def __str__(self) -> str:
        args_str = " ".join(self.args) if self.args else ""
        full_cmd = f"{self.cmd} {args_str}".strip()
        return f"PID {self.pid}: {full_cmd} (cwd: {self.cwd})"


@dataclass
class CommandResult:
    """Result of a command execution"""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    execution_time: float
    pid: Optional[int] = None
    status: ProcessStatus = ProcessStatus.COMPLETED
    error_message: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

        # Determine status based on exit code if not set
        if self.exit_code == 0:
            self.status = ProcessStatus.COMPLETED
        elif self.exit_code != 0:
            self.status = ProcessStatus.FAILED

    @property
    def success(self) -> bool:
        """Whether command executed successfully"""
        return self.exit_code == 0

    @property
    def failed(self) -> bool:
        """Whether command failed"""
        return not self.success

    def get_summary(self) -> str:
        """Get human-readable summary"""
        status_str = "✓" if self.success else "✗"
        cmd_preview = (
            self.command[:50] + "..." if len(self.command) > 50 else self.command
        )

        return (
            f"[{status_str}] {cmd_preview} | "
            f"Exit: {self.exit_code} | "
            f"Time: {self.execution_time:.2f}s"
        )


@dataclass
class ServiceInfo:
    """Information about a running service"""

    pid: int
    service_type: ServiceType
    command: str
    port: Optional[int] = None
    public_url: Optional[str] = None
    started_at: datetime = None
    description: Optional[str] = None

    def __post_init__(self):
        if self.started_at is None:
            self.started_at = datetime.now(timezone.utc)

    def get_info(self) -> str:
        """Get formatted service information"""
        info = f"Service PID {self.pid} ({self.service_type.value})"
        if self.port:
            info += f" on port {self.port}"
        if self.public_url:
            info += f"\nPublic URL: {self.public_url}"
        if self.description:
            info += f"\nDescription: {self.description}"
        return info


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Create a structured logger for command operations"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    return logger


def validate_command(command: str) -> str:
    """
    Validate command for security and safety.

    Args:
        command: Command string to validate

    Returns:
        Validated command string

    Raises:
        ValueError: If command is invalid or dangerous
    """
    if not command or not isinstance(command, str):
        raise ValueError("Command must be a non-empty string")

    command = command.strip()
    if not command:
        raise ValueError("Command cannot be empty")

    # Security checks - prevent extremely dangerous operations
    dangerous_patterns = [
        "rm -rf /",
        "rm -rf /*",
        "format",
        "mkfs",
        "> /dev/sda",
    ]

    command_lower = command.lower()
    for pattern in dangerous_patterns:
        if pattern in command_lower:
            raise ValueError(
                f"Extremely dangerous command pattern detected: '{pattern}'. "
                f"This operation is blocked for safety."
            )

    return command


# Global logger
_logger = setup_logger("command_tools_langgraph")

# Global tracking for services (per-process, since we use config now)
_running_services: Dict[int, ServiceInfo] = {}
_background_commands: Dict[int, Any] = {}

# Settings
_settings = {
    "default_timeout": 60,
    "max_output_size": 1024 * 1024,
}


def configure_command_tools(
    default_timeout: int = 60, max_output_size: int = 1024 * 1024
):
    """Configure command tools settings"""
    _settings["default_timeout"] = default_timeout
    _settings["max_output_size"] = max_output_size


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


async def _sync_if_needed(
    sandbox, command: str, user_id: str, project_id: str
) -> Optional[str]:
    """
    Simple keyword-based dependency sync.
    Syncs dependency files to database when command contains keywords.
    """
    # Keywords that indicate dependency changes
    sync_patterns = [
        # Node.js package managers with operations
        "npm install",
        "npm uninstall",
        "npm remove",
        "npm update",
        "npm add",
        "yarn add",
        "yarn remove",
        "yarn install",
        "yarn upgrade",
        "pnpm install",
        "pnpm add",
        "pnpm remove",
        "pnpm update",
        "bun install",
        "bun add",
        "bun remove",
        # Python package managers with operations
        "pip install",
        "pip uninstall",
        "pip upgrade",
        "pip3 install",
        "conda install",
        "conda remove",
        "conda update",
        "poetry add",
        "poetry remove",
        "poetry install",
        "poetry update",
        "pipenv install",
        "pipenv uninstall",
        # System package managers
        "apt install",
        "apt remove",
        "apt update",
        "apt upgrade",
        "apt-get install",
        "apt-get remove",
        "apt-get update",
        "apt-get upgrade",
        "yum install",
        "yum remove",
        "yum update",
        "brew install",
        "brew uninstall",
        "brew upgrade",
        # Other package managers
        "composer install",
        "composer require",
        "composer remove",
        "bundle install",
        "gem install",
        "gem uninstall",
        "cargo install",
        "go mod tidy",
        "go get",
    ]

    # Check if command contains sync keywords
    command_lower = command.lower().strip()
    needs_sync = False
    for pattern in sync_patterns:
        words = command_lower.split()
        pattern_words = pattern.split()
        for i in range(len(words) - len(pattern_words) + 1):
            if words[i : i + len(pattern_words)] == pattern_words:
                needs_sync = True
                break
        if needs_sync:
            break

    if not needs_sync:
        return None

    # Critical dependency files to sync
    # Supports both meme-coin-base-v0 (/home/user/project/) and legacy templates
    dependency_files = [
        "/home/user/project/package.json",
        "/home/user/project/yarn.lock",
        "/home/user/code/frontend/package.json",
        # "/home/user/code/frontend/package-lock.json",
        "/home/user/code/frontend/yarn.lock",
        "/home/user/code/backend/requirements.txt",
        "/home/user/code/backend/pyproject.toml",
        "/home/user/code/backend/poetry.lock",
    ]

    # Sync files that exist
    synced_files = []
    try:
        for file_path in dependency_files:
            try:
                # Check if file exists
                exists = await sandbox.files.exists(file_path)
                if not exists:
                    continue

                # Read file content
                content = await sandbox.files.read(file_path)
                if not content:
                    continue

                # Save to database using improved persistence
                await _persist_file_to_db(
                    user_id, project_id, file_path, content, "command_sync"
                )

                synced_files.append(file_path.split("/")[-1])  # Just filename
            except Exception as e:
                _logger.debug(f"Could not sync {file_path}: {e}")
                continue

        if synced_files:
            return f"Dependency Sync: {len(synced_files)} files synced ({', '.join(synced_files)})"
        else:
            return "Dependency Sync: No dependency files found to sync"
    except Exception as e:
        _logger.error(f"Dependency sync failed: {e}")
        return f"Dependency Sync: Failed ({str(e)})"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# Configuration
_default_config = {
    "enable_db_tracking": True,
}


def configure_command_tools(enable_db_tracking: bool = True):
    """Configure command tools settings"""
    _default_config["enable_db_tracking"] = enable_db_tracking


async def _persist_file_to_db(
    user_id: str, project_id: str, path: str, content: str, tool_name: str
):
    """Persist file changes to database"""

    try:
        # NEW: Just save the file, assume project exists
        # NestJS validated ownership before proxying request
        # # Create user/project with better error handling
        # try:
        #     await db_service.create_user(user_id, email)
        # except Exception as user_err:
        #     # User creation might fail due to IntegrityError (race condition)
        #     # This is OK - user likely exists
        #     _logger.debug(
        #         f"User {user_id} already exists or creation failed: {user_err}"
        #     )

        # try:
        #     await db_service.create_project(
        #         user_id, project_id, f"Project {project_id}"
        #     )
        # except Exception as proj_err:
        #     # Project creation might fail if already exists
        #     _logger.debug(
        #         f"Project {project_id} already exists or creation failed: {proj_err}"
        #     )

        # Now save the file
        success = await db_service.save_file(
            project_id=project_id,
            file_path=path,
            content=content,
            created_by_tool=tool_name,
        )

        if success:
            _logger.info(f"DB: Persisted {path}")
        else:
            _logger.error(f"DB: Failed to persist {path}")

    except Exception as e:
        _logger.error(f"DB persist exception for {path}: {e}", exc_info=True)


# =============================================================================
# CORE COMMAND TOOLS
# =============================================================================


@tool
async def run_command(
    command: str,
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState],
    background: bool = False,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    envs: Optional[Dict[str, str]] = None,
    # Service-related parameters (only used when background=True)
    port: Optional[int] = None,
) -> str:
    """
    Run a shell command either synchronously (wait for completion) or in the background (for services).

    Use background=False (default) for short-running commands like:
    - `ls`, `echo`, `cat`, `grep`
    - `npm install`, `pip install`
    - `git status`, `git commit`
    - Any command that should complete and return output

    Use background=True for long-running services like:
    - Web servers: `npm run dev`, `python app.py`
    - API servers: `uvicorn main:app`, `node server.js`
    - Frontend dev servers: `npm start`, `yarn dev`
    - Database servers, background tasks, etc.

    Args:
        command: Shell command to execute
        background: If True, run command in background (for services). If False, wait for completion (default: False)
        timeout: Timeout in seconds for foreground commands (default: 60s). Ignored when background=True
        cwd: Working directory to run the command in
        envs: Environment variables for the command
        port: Port number for background services (optional, used to generate public URL)

    Returns:
        For foreground (background=False):
            Formatted string with command results (stdout, stderr, exit code, execution time)
        For background (background=True):
            Service information (PID, port, public URL if port specified)
    """
    # Get user_id and project_id from runtime context or state
    user_id = None
    project_id = None

    try:
        if hasattr(runtime, "context") and runtime.context:
            user_id = getattr(runtime.context, "user_id", None)
            project_id = getattr(runtime.context, "project_id", None)
    except Exception:
        pass

    # Fallback to state if context doesn't have values
    if not user_id or not project_id:
        try:
            if hasattr(runtime, "state") and runtime.state:
                if isinstance(runtime.state, dict):
                    user_id = runtime.state.get("user_id") or user_id
                    project_id = runtime.state.get("project_id") or project_id
                else:
                    user_id = getattr(runtime.state, "user_id", None) or user_id
                    project_id = (
                        getattr(runtime.state, "project_id", None) or project_id
                    )
        except Exception:
            pass

    # Final safety check
    if not user_id or not project_id:
        return "ERROR: Missing user_id or project_id in runtime context and state. Cannot access sandbox."

    # Validate input parameters
    try:
        if not command or not isinstance(command, str):
            return "ERROR: Command must be a non-empty string."

        if background and port is not None:
            if not isinstance(port, int) or port < 1 or port > 65535:
                return f"ERROR: Invalid port number: {port}. Port must be between 1 and 65535."

        if timeout is not None:
            if not isinstance(timeout, (int, float)) or timeout <= 0:
                return f"ERROR: Invalid timeout: {timeout}. Timeout must be a positive number."

        if cwd is not None and not isinstance(cwd, str):
            return "ERROR: cwd must be a string path."

        if envs is not None and not isinstance(envs, dict):
            return "ERROR: envs must be a dictionary of environment variables."

    except Exception as e:
        return f"ERROR: Parameter validation failed: {str(e)}"

    try:
        sandbox = await get_user_sandbox(user_id, project_id)
    except Exception as e:
        _logger.error(f"Failed to get sandbox: {e}")
        return f"ERROR: Failed to access sandbox. {str(e)}"

    try:
        # Validate command (may raise ValueError)
        validated_command = validate_command(command)
    except ValueError as e:
        # Return formatted error string instead of raising
        return f"ERROR: Command validation failed: {str(e)}"
    except Exception as e:
        return f"ERROR: Command validation error: {str(e)}"

    # ====================================================================
    # BACKGROUND EXECUTION (for services)
    # ====================================================================
    if background:
        try:
            _logger.info(
                f"Starting background service: {validated_command[:100]}... "
                f"(port={port}, cwd={cwd or '/home/user/project'})"
            )

            # Execute command in background
            process = await sandbox.commands.run(
                validated_command,
                envs=envs,
                cwd=cwd or "/home/user/project",
                background=True,
            )

            # Get PID from the background process handle
            pid = process.pid

            # Track the command handle for later use
            _background_commands[pid] = process

            # Get public URL if port is specified
            public_url = None
            if port:
                # Wait a moment for service to start
                await asyncio.sleep(2)

                try:
                    host = sandbox.get_host(port)
                    public_url = f"https://{host}"
                    _logger.info(f"Service available at: {public_url}")
                except Exception as e:
                    _logger.warning(f"Could not get public URL for port {port}: {e}")

            # Create service info (using CUSTOM type for simplicity)
            service_info = ServiceInfo(
                pid=pid,
                service_type=ServiceType.CUSTOM,
                command=validated_command,
                port=port,
                public_url=public_url,
                description=(
                    f"Background service on port {port}"
                    if port
                    else "Background service"
                ),
            )

            # Track the service
            _running_services[pid] = service_info

            # Format output for agent
            output = f"✓ Service started successfully in background!\n\n"
            output += f"PID: {pid}\n"
            output += f"Command: {validated_command}\n"
            if port:
                output += f"Port: {port}\n"
            if public_url:
                output += f"\n🌐 Public URL: {public_url}\n"
                output += f"You can access the service at: {public_url}\n"

            output += f"\nUse kill_process({pid}) to stop this service.\n"

            _logger.info(f"Service started - PID: {pid}")
            return output

        except Exception as e:
            _logger.error(f"Failed to start background service: {e}")
            return f"ERROR: Failed to start background service: {str(e)}"

    # ====================================================================
    # FOREGROUND EXECUTION (wait for completion)
    # ====================================================================
    else:
        try:
            timeout = timeout or _settings["default_timeout"]

            _logger.info(
                f"Executing command: {validated_command[:100]}... "
                f"(timeout={timeout}s, cwd={cwd or '/home/user/project'})"
            )

            start_time = datetime.now()

            # Execute command in sandbox (foreground - waits for completion)
            result = await sandbox.commands.run(
                validated_command,
                timeout=timeout,
                cwd=cwd or "/home/user/project",
                envs=envs,
            )

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            # Create result object
            cmd_result = CommandResult(
                command=validated_command,
                exit_code=result.exit_code,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                execution_time=execution_time,
                error_message=result.error if hasattr(result, "error") else None,
            )

            # Dependency sync if needed
            sync_status = await _sync_if_needed(
                sandbox, validated_command, user_id, project_id
            )

            # Log result
            _logger.info(f"Command completed: {cmd_result.get_summary()}")

            # Format output for agent
            output = f"Command: {validated_command}\n"
            output += f"Exit Code: {result.exit_code}\n"
            output += f"Execution Time: {execution_time:.2f}s\n"
            output += f"Status: {'✓ Success' if cmd_result.success else '✗ Failed'}\n"

            # Add sync status if sync occurred
            if sync_status:
                output += f"{sync_status}\n"

            output += "\n"

            if result.stdout:
                output += f"=== STDOUT ===\n{result.stdout}\n\n"
            if result.stderr:
                output += f"=== STDERR ===\n{result.stderr}\n\n"
            if cmd_result.error_message:
                output += f"=== ERROR ===\n{cmd_result.error_message}\n"

            return output

        except Exception as e:
            error_msg = str(e).lower()
            if "timeout" in error_msg or "timed out" in error_msg:
                _logger.error(f"Command timed out: {e}")
                timeout_val = timeout or _settings["default_timeout"]
                timeout_msg = f"Command timed out after {timeout_val} seconds."
                suggestion = "Consider increasing timeout or using background=True for long-running services."
                return f"ERROR: {timeout_msg} {suggestion}\nDetails: {str(e)}"
            else:
                _logger.error(f"Command execution failed: {e}")
                return f"ERROR: Command execution failed: {str(e)}"


@tool
async def list_processes(
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState],
) -> str:
    """
    List all running processes in the sandbox.

    Args:
        config: LangGraph config with user/project context (REQUIRED)

    Returns:
        Formatted list of all running processes with details
    """
    user_id = runtime.context.user_id
    project_id = runtime.context.project_id
    if not user_id or not project_id:
        user_id = runtime.state["user_id"]
        project_id = runtime.state["project_id"]

    # Final safety check
    if not user_id or not project_id:
        return f"ERROR: Missing user_id or project_id in runtime context and state. Cannot access sandbox."

    try:
        sandbox = await get_user_sandbox(user_id, project_id)

        # Use E2B's list method to get all running processes
        processes = await sandbox.commands.list()

        if not processes:
            return "No processes currently running in the sandbox."

        # Format output
        output = f"=== Running Processes ({len(processes)}) ===\n\n"

        for proc in processes:
            # Convert to our ProcessInfo type
            proc_info = ProcessInfo(
                pid=proc.pid,
                tag=proc.tag or "",
                cmd=proc.cmd,
                args=list(proc.args) if proc.args else [],
                envs=dict(proc.envs) if proc.envs else {},
                cwd=proc.cwd or "/",
            )

            output += f"PID: {proc_info.pid}\n"
            output += f"Command: {proc_info.cmd}\n"
            if proc_info.args:
                output += f"Args: {' '.join(proc_info.args)}\n"
            output += f"CWD: {proc_info.cwd}\n"
            if proc_info.tag:
                output += f"Tag: {proc_info.tag}\n"

            # Check if this is a tracked service
            if proc_info.pid in _running_services:
                service = _running_services[proc_info.pid]
                output += f"Service Type: {service.service_type.value}\n"
                if service.port:
                    output += f"Port: {service.port}\n"
                if service.public_url:
                    output += f"URL: {service.public_url}\n"

            output += "\n" + "-" * 60 + "\n\n"

        _logger.info(f"Listed {len(processes)} running processes")
        return output

    except Exception as e:
        _logger.error(f"Failed to list processes: {e}")
        return json.dumps(
            {"status": "error", "message": f"Failed to list processes: {str(e)}"}
        )


@tool
async def kill_process(
    pid: int, runtime: ToolRuntime[RuntimeContext, LandingPageAgentState]
) -> str:
    """
    Kill a running process by its PID.

    This sends a SIGKILL signal to the process, immediately terminating it.
    Use this to stop services started with run_command(background=True) or any other running process.

    Args:
        pid: Process ID to kill
        config: LangGraph config with user/project context (REQUIRED)

    Returns:
        Status message indicating whether process was killed
    """
    user_id = runtime.context.user_id
    project_id = runtime.context.project_id
    if not user_id or project_id:
        user_id = runtime.state["user_id"]
        project_id = runtime.state["project_id"]

    # Final safety check
    if not user_id or not project_id:
        return f"ERROR: Missing user_id or project_id in runtime context and state. Cannot access sandbox."

    try:
        sandbox = await get_user_sandbox(user_id, project_id)

        if not isinstance(pid, int) or pid <= 0:
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Invalid PID: {pid}. PID must be a positive integer.",
                }
            )

        _logger.info(f"Killing process: {pid}")

        # Use E2B's kill method
        killed = await sandbox.commands.kill(pid)

        # Remove from tracked services if it was a service
        service_info = _running_services.pop(pid, None)

        # Remove from background commands
        cmd_handle = _background_commands.pop(pid, None)

        if killed:
            output = f"✓ Successfully killed process {pid}\n"
            if service_info:
                output += f"\nService Details:\n"
                output += f"Type: {service_info.service_type.value}\n"
                output += f"Command: {service_info.command}\n"
                if service_info.port:
                    output += f"Port: {service_info.port}\n"
            _logger.info(f"Successfully killed process {pid}")
        else:
            output = f"Process {pid} not found or already terminated.\n"
            _logger.warning(f"Process {pid} not found")

        return output

    except Exception as e:
        _logger.error(f"Failed to kill process {pid}: {e}")
        return json.dumps(
            {
                "status": "error",
                "message": f"Failed to kill process {pid}: {str(e)}",
            }
        )


# @tool
# async def get_service_url(
#     port: int,
#     runtime: ToolRuntime[RuntimeContext, LandingPageAgentState],
# ) -> str:
#     """
#     Get the public URL for a service running on a specific port.
#
#     Args:
#         port: Port number the service is listening on
#         config: LangGraph config with user/project context (REQUIRED)
#
#     Returns:
#         Public URL for the service
#     """
#     user_id = runtime.context.user_id
#     project_id = runtime.context.project_id
#     if not user_id or project_id:
#         user_id = runtime.state["user_id"]
#         project_id = runtime.state["project_id"]
#
#     # Final safety check
#     if not user_id or not project_id:
#         return f"ERROR: Missing user_id or project_id in runtime context and state. Cannot access sandbox."
#
#     try:
#         sandbox = await get_user_sandbox(user_id, project_id)
#
#         if not isinstance(port, int) or port <= 0 or port > 65535:
#             return json.dumps(
#                 {
#                     "status": "error",
#                     "message": f"Invalid port: {port}. Port must be between 1 and 65535.",
#                 }
#             )
#
#         _logger.info(f"Getting public URL for port {port}")
#
#         # Use E2B's get_host method
#         host = sandbox.get_host(port)
#         url = f"http://{host}"
#
#         output = f"Public URL for port {port}:\n{url}\n"
#         _logger.info(f"Generated URL for port {port}: {url}")
#         return output
#
#     except Exception as e:
#         _logger.error(f"Failed to get URL for port {port}: {e}")
#         return json.dumps(
#             {
#                 "status": "error",
#                 "message": f"Failed to get URL for port {port}. Ensure a service is running on this port. Error: {str(e)}",
#             }
#         )


# =============================================================================
# COMMENTED TOOLS (Retained for future use)
# =============================================================================


@tool
async def send_stdin(
    pid: int, data: str, runtime: ToolRuntime[RuntimeContext, LandingPageAgentState]
) -> str:
    """
    Send data to a process's stdin stream.

    Use this for interactive commands that accept stdin input.

    Args:
        pid: Process ID to send data to
        data: String data to send to stdin
        config: LangGraph config with user/project context (REQUIRED)

    Returns:
        Status message
    """
    user_id = runtime.context.user_id
    project_id = runtime.context.project_id

    # Final safety check
    if not user_id or not project_id:
        return f"ERROR: Missing user_id or project_id in runtime context and state. Cannot access sandbox."

    try:
        sandbox = await get_user_sandbox(user_id, project_id)

        if not isinstance(pid, int) or pid <= 0:
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Invalid PID: {pid}. PID must be a positive integer.",
                }
            )

        if not isinstance(data, str):
            return json.dumps({"status": "error", "message": "Data must be a string"})

        _logger.info(f"Sending stdin to process {pid}: {len(data)} chars")

        # Use E2B's send_stdin method
        await sandbox.commands.send_stdin(pid, data)

        output = f"✓ Successfully sent {len(data)} characters to process {pid}\n"
        _logger.info(f"Sent stdin to process {pid}")
        return output

    except Exception as e:
        _logger.error(f"Failed to send stdin to process {pid}: {e}")
        return json.dumps(
            {
                "status": "error",
                "message": f"Failed to send stdin to process {pid}: {str(e)}",
            }
        )


@tool
async def list_services(
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState],
) -> str:
    """
    List all tracked running services.

    Args:
        config: LangGraph config with user/project context (REQUIRED)

    Returns:
        Formatted list of all tracked services
    """
    try:
        if not _running_services:
            return "No tracked services currently running."

        output = f"=== Tracked Services ({len(_running_services)}) ===\n\n"

        for pid, service in _running_services.items():
            output += f"PID: {pid}\n"
            output += f"Type: {service.service_type.value}\n"
            output += f"Command: {service.command}\n"
            if service.port:
                output += f"Port: {service.port}\n"
            if service.public_url:
                output += f"URL: {service.public_url}\n"
            if service.description:
                output += f"Description: {service.description}\n"
            output += (
                f"Started: {service.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            )
            output += "\n" + "-" * 60 + "\n\n"

        return output

    except Exception as e:
        _logger.error(f"Failed to list services: {e}")
        return json.dumps(
            {"status": "error", "message": f"Failed to list services: {str(e)}"}
        )


@tool
async def connect_to_process(
    pid: int,
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState],
    timeout: Optional[int] = None,
) -> str:
    """
    Connect to an existing running process to receive its output.

    Useful for reconnecting to processes that were started in the background
    or to monitor already running processes.

    Args:
        pid: Process ID to connect to
        config: LangGraph config with user/project context (REQUIRED)
        timeout: Connection timeout in seconds

    Returns:
        Connection status message
    """
    user_id = runtime.context.user_id
    project_id = runtime.context.project_id

    # Final safety check
    if not user_id or not project_id:
        return f"ERROR: Missing user_id or project_id in runtime context and state. Cannot access sandbox."

    try:
        sandbox = await get_user_sandbox(user_id, project_id)

        if not isinstance(pid, int) or pid <= 0:
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Invalid PID: {pid}. PID must be a positive integer.",
                }
            )

        _logger.info(f"Connecting to process {pid}")

        # Use E2B's connect method
        cmd_handle = await sandbox.commands.connect(
            pid=pid,
            timeout=timeout or _settings["default_timeout"],
        )

        # Store the command handle
        _background_commands[pid] = cmd_handle

        output = f"✓ Successfully connected to process {pid}\n"
        output += f"You can now interact with this process using send_stdin or kill_process.\n"

        _logger.info(f"Connected to process {pid}")
        return output

    except Exception as e:
        _logger.error(f"Failed to connect to process {pid}: {e}")
        return json.dumps(
            {
                "status": "error",
                "message": f"Failed to connect to process {pid}: {str(e)}",
            }
        )


# =============================================================================
# TOOL EXPORT
# =============================================================================

# All command tools (including commented ones)
COMMAND_TOOLS = [
    run_command,  # Unified tool - handles both foreground and background execution
    list_processes,
    kill_process,
    # get_service_url,  # Commented - explicit API route available for getting public URL
    # send_stdin,  # Commented tool - retained
    # list_services,  # Commented tool - retained
    # connect_to_process,  # Commented tool - retained
]

# Core tools only (most commonly used)
CORE_COMMAND_TOOLS = [
    run_command,  # Unified tool - handles both foreground and background execution
    list_processes,
    kill_process,
    # get_service_url,  # Commented - explicit API route available for getting public URL
]

if __name__ == "__main__":
    print("CommandTools for LangGraph - E2B Sandbox Command Operations")
    print(f"Available tools: {len(COMMAND_TOOLS)}")
    print("Core tools:", [t.name for t in CORE_COMMAND_TOOLS])
    print("All tools:", [t.name for t in COMMAND_TOOLS])
    print("\nAll methods retained including commented tools!")
    print("Automatic dependency syncing enabled!")
    print("Ready for LangGraph agents!")

