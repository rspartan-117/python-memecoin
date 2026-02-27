"""
E2B Sandbox Session Management API Routes

This module provides API endpoints for managing E2B sandbox sessions:
- Create/Get sandbox session for user_id and project_id
- Pause sandbox session and update expiration time
- Resume sandbox session
- Get public URLs for ports (3000, 8000)
"""

import asyncio
import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from sandbox_manager import (
    get_multi_tenant_manager,
    get_user_sandbox,
    SandboxResourceLimitError,
)
from e2b import AsyncSandbox
from e2b.exceptions import (
    SandboxException,
    AuthenticationException,
    NotFoundException,
    TimeoutException,
)
from db import get_db_session
from db.data_access import ProjectRepository
from db.models import Project, SandboxState

logger = logging.getLogger("api.sandbox")

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class CreateSandboxSessionRequest(BaseModel):
    """Request model for creating a sandbox session"""

    user_id: str = Field(..., description="User ID", min_length=1, max_length=255)
    project_id: str = Field(
        ...,
        description="Project ID (session_id == project_id)",
        min_length=1,
        max_length=255,
    )


class CreateSandboxSessionResponse(BaseModel):
    """Response model for creating a sandbox session"""

    success: bool
    sandbox_id: str
    user_id: str
    project_id: str
    frontend_url: Optional[str] = None  # Port 3000
    backend_url: Optional[str] = None  # Port 8000
    message: str


class PauseSandboxSessionRequest(BaseModel):
    """Request model for pausing a sandbox session"""

    user_id: str = Field(..., description="User ID", min_length=1, max_length=255)
    project_id: str = Field(..., description="Project ID", min_length=1, max_length=255)


class PauseSandboxSessionResponse(BaseModel):
    """Response model for pausing a sandbox session"""

    success: bool
    sandbox_id: str
    paused: bool
    message: str


class ResumeSandboxSessionRequest(BaseModel):
    """Request model for resuming a sandbox session"""

    user_id: str = Field(..., description="User ID", min_length=1, max_length=255)
    project_id: str = Field(..., description="Project ID", min_length=1, max_length=255)


class ResumeSandboxSessionResponse(BaseModel):
    """Response model for resuming a sandbox session"""

    success: bool
    sandbox_id: str
    resumed: bool
    message: str


class PublicURLRequest(BaseModel):
    """Request model for getting public URL"""

    user_id: str = Field(..., description="User ID", example="user_123")
    project_id: str = Field(..., description="Project ID", example="project_456")
    port: int = Field(..., description="Port number (3000 or 8000)", ge=1, le=65535, example=3000)


class PublicURLResponse(BaseModel):
    """Response model for public URL"""

    success: bool
    sandbox_id: str
    port: int
    public_url: str
    message: str


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


async def _get_sandbox_id_from_redis(user_id: str, project_id: str) -> Optional[str]:
    """
    Get sandbox ID from Redis general cache (30 min TTL).

    Note: This only checks the general cache. For complete sandbox retrieval
    including long-term cache (30 days) and database, use get_user_sandbox().
    """
    try:
        manager = await get_multi_tenant_manager()
        # Access the private method via the manager instance
        # This checks only the general cache (30 min TTL)
        sandbox_id = await manager._get_cached_sandbox_id(user_id, project_id)
        if sandbox_id:
            # Handle bytes decoding if needed
            if isinstance(sandbox_id, bytes):
                return sandbox_id.decode("utf-8")
            return str(sandbox_id)
        return None
    except Exception as e:
        logger.warning(f"Failed to get sandbox_id from Redis general cache: {e}")
        return None


async def _get_sandbox_id_from_all_sources(
    user_id: str, project_id: str
) -> Optional[str]:
    """
    Get sandbox ID from all available sources in order:
    1. General cache (Redis 30 min TTL)
    2. Long-term cache (Redis 30 days TTL)
    3. Database (permanent source of truth)

    This is used by the /resume endpoint to find paused sandboxes.

    Returns:
        sandbox_id if found, None otherwise
    """
    try:
        manager = await get_multi_tenant_manager()

        # Step 1: Check general cache (30 min)
        sandbox_id = await manager._get_cached_sandbox_id(user_id, project_id)
        if sandbox_id:
            logger.info(f"Found sandbox_id in general cache for {user_id}/{project_id}")
            if isinstance(sandbox_id, bytes):
                return sandbox_id.decode("utf-8")
            return str(sandbox_id)

        # Step 2: Check long-term cache (30 days)
        sandbox_id = await manager._get_longterm_sandbox_id(user_id, project_id)
        if sandbox_id:
            logger.info(
                f"Found sandbox_id in long-term cache for {user_id}/{project_id}"
            )
            if isinstance(sandbox_id, bytes):
                return sandbox_id.decode("utf-8")
            return str(sandbox_id)

        # Step 3: Check database
        project = await manager._get_project_from_db(project_id)
        if project and project.active_sandbox_id:
            # Check if sandbox is not killed (based on lifecycle)
            is_killed = await manager._is_sandbox_killed(project)
            if not is_killed:
                logger.info(f"Found sandbox_id in database for {user_id}/{project_id}")
                return project.active_sandbox_id
            else:
                logger.info(
                    f"Sandbox in database is killed (lifecycle expired) for {user_id}/{project_id}"
                )

        logger.info(f"No sandbox_id found in any source for {user_id}/{project_id}")
        return None

    except Exception as e:
        logger.error(
            f"Failed to get sandbox_id from all sources for {user_id}/{project_id}: {e}"
        )
        return None


async def _get_sandbox_by_id_or_redis(
    sandbox_id: Optional[str],
    user_id: Optional[str],
    project_id: Optional[str],
) -> tuple[AsyncSandbox, str]:
    """
    Get sandbox instance either by sandbox_id or by looking up using user_id/project_id.

    This function uses the complete retrieval flow:
    1. General cache (Redis 30 min)
    2. Long-term cache (Redis 30 days)
    3. Database (permanent source of truth)
    4. Create new if needed

    Returns:
        tuple: (sandbox_instance, sandbox_id)
    """
    manager = await get_multi_tenant_manager()

    if sandbox_id:
        # Use provided sandbox_id
        try:
            sandbox = await AsyncSandbox.connect(
                sandbox_id,
                api_key=manager._config.api_key,
            )
            return sandbox, sandbox_id
        except Exception as e:
            raise HTTPException(
                status_code=404,
                detail=f"Failed to connect to sandbox {sandbox_id}: {str(e)}",
            )

    # Need user_id and project_id to look up from Redis
    if not user_id or not project_id:
        raise HTTPException(
            status_code=400,
            detail="Either sandbox_id or both user_id and project_id must be provided",
        )

    # Try to get from Redis
    cached_sandbox_id = await _get_sandbox_id_from_redis(user_id, project_id)

    if cached_sandbox_id:
        try:
            sandbox = await AsyncSandbox.connect(
                cached_sandbox_id,
                api_key=manager._config.api_key,
            )
            return sandbox, cached_sandbox_id
        except Exception as e:
            # If connection fails, try to get/create from manager
            logger.warning(
                f"Failed to connect to cached sandbox {cached_sandbox_id}: {e}, trying to get/create new one"
            )
            try:
                sandbox = await get_user_sandbox(user_id, project_id)
                return sandbox, sandbox.sandbox_id
            except Exception as e2:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to get sandbox for user {user_id}, project {project_id}: {str(e2)}",
                )
    else:
        # Try to get/create from manager
        try:
            sandbox = await get_user_sandbox(user_id, project_id)
            return sandbox, sandbox.sandbox_id
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get sandbox for user {user_id}, project {project_id}: {str(e)}",
            )


# =============================================================================
# API ENDPOINTS
# =============================================================================


@router.post("/session", response_model=CreateSandboxSessionResponse)
async def get_or_create_session(request: CreateSandboxSessionRequest):
    """
    Get or create sandbox session for user_id and project_id.

    This is the PRIMARY endpoint for sandbox management. It intelligently:
    - Returns existing sandbox if found (from memory, cache, or database)
    - Creates new sandbox only if needed
    - Automatically resumes paused sandboxes
    - Handles session restoration for existing projects

    Four-step retrieval flow:
    1. Memory pool (L1 - instant, active sandboxes)
    2. General cache (Redis 30 min - recently used)
    3. Long-term cache (Redis 30 days - paused/standby)
    4. Database (permanent fallback)

    Features:
    - Two-layer Redis caching for performance
    - Database as source of truth
    - 30-day sandbox lifecycle management
    - Automatic session restoration
    - Graceful handling of missing database records

    Use this endpoint for:
    - Initial sandbox creation
    - Reconnecting to existing sandboxes
    - Resuming paused sandboxes
    - General sandbox retrieval
    """
    try:
        logger.info(
            f"Getting/creating sandbox session for user={request.user_id}, project={request.project_id}"
        )

        # =====================================================================
        # TODO: REMOVE AFTER TESTING - Temporary project creation for Python-only testing
        # =====================================================================
        # In production, NestJS backend creates projects in DB before calling Python.
        # This temporary code allows direct Python testing without NestJS.
        # Remove this block once NestJS integration is complete!
        # =====================================================================
        try:
            async with get_db_session() as session:
                project_repo = ProjectRepository(session)

                # Check if project exists
                existing_project = await project_repo.get_project(request.project_id)

                if not existing_project:
                    # Create project in DB (temporary for testing)
                    logger.warning(
                        f"[TEMP] Creating project in DB for testing: {request.project_id}. "
                        f"In production, NestJS should create this!"
                    )

                    new_project = Project(
                        id=request.project_id,
                        userId=request.user_id,
                        name=f"Test Project {request.project_id[:8]}",  # Temporary name
                        sandbox_state=SandboxState.NONE,
                        status="ACTIVE",  # SessionStatus ENUM
                        type="FULLSTACK",  # ProjectType ENUM (default)
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                        last_active=datetime.now(),
                    )

                    session.add(new_project)
                    await session.commit()

                    logger.info(
                        f"[TEMP] Created project {request.project_id} in DB for testing"
                    )
                else:
                    logger.debug(f"Project {request.project_id} already exists in DB")

        except Exception as e:
            # Log error but don't fail the request
            # The sandbox_manager will handle missing DB records gracefully
            logger.warning(
                f"[TEMP] Failed to create project in DB: {e}. "
                f"Continuing with sandbox creation (manager handles missing DB records)."
            )
        # =====================================================================
        # END TODO - REMOVE AFTER TESTING
        # =====================================================================

        # Get or create sandbox (this handles Redis caching internally)
        sandbox = await get_user_sandbox(request.user_id, request.project_id)

        # Small delay to ensure sandbox is fully initialized
        await asyncio.sleep(0.5)

        # Get public URLs for ports 3000 and 8000
        # get_host() returns the preview URL format: {port}-{sandbox_id}.e2b.app
        try:
            frontend_url = f"https://{sandbox.get_host(3000)}"
            logger.info(f"Frontend URL (port 3000): {frontend_url}")
        except Exception as e:
            logger.warning(f"Failed to get frontend URL (port 3000): {e}")
            frontend_url = None

        try:
            backend_url = f"https://{sandbox.get_host(8000)}"
            logger.info(f"Backend URL (port 8000): {backend_url}")
        except Exception as e:
            logger.warning(f"Failed to get backend URL (port 8000): {e}")
            backend_url = None

        return JSONResponse(
            status_code=200,
            content=CreateSandboxSessionResponse(
                success=True,
                sandbox_id=sandbox.sandbox_id,
                user_id=request.user_id,
                project_id=request.project_id,
                frontend_url=frontend_url,
                backend_url=backend_url,
                message=f"Sandbox session created/retrieved successfully",
            ).model_dump(),
        )

    except SandboxResourceLimitError as e:
        # Return 429 Too Many Requests with structured error
        logger.warning(
            f"Resource limit exceeded for user={request.user_id}, project={request.project_id}: {e.message}"
        )
        error_response = e.to_dict()
        raise HTTPException(status_code=429, detail=error_response)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to create session: {str(e)}"
        )


@router.post("/pause", response_model=PauseSandboxSessionResponse)
async def pause_session(request: PauseSandboxSessionRequest):
    """
    Pause sandbox session.

    This endpoint will:
    - Pause the sandbox (saves state, stops billing)
    - Remove from L1 memory pool (saves memory)
    - Remove from general cache (30 min TTL)
    - Keep in long-term cache (30 days) for recovery
    - Update database state to PAUSED

    Recovery:
    - Sandbox can be resumed via /session or /resume endpoints
    - Long-term cache maintains sandbox for 30 days
    - Database maintains state for persistence beyond cache expiry

    Args:
        request: PauseSandboxSessionRequest containing user_id and project_id

    Returns:
        PauseSandboxSessionResponse with pause status
    """
    try:
        manager = await get_multi_tenant_manager()

        logger.info(
            f"Pausing sandbox for user={request.user_id}, project={request.project_id}"
        )

        # Use manager's pause method which handles all caching and state management
        try:
            sandbox_id = await manager.pause_sandbox(
                request.user_id, request.project_id
            )
            logger.info(
                f"Sandbox {sandbox_id} paused successfully for {request.user_id}/{request.project_id}"
            )

        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to pause sandbox: {str(e)}"
            )

        return JSONResponse(
            status_code=200,
            content=PauseSandboxSessionResponse(
                success=True,
                sandbox_id=sandbox_id,
                paused=True,
                message=f"Sandbox {sandbox_id} paused successfully. Recoverable via long-term cache (30 days) or database.",
            ).model_dump(),
        )

    except HTTPException:
        raise
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to pause session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to pause session: {str(e)}"
        )


@router.post("/resume", response_model=ResumeSandboxSessionResponse)
async def resume_session(request: ResumeSandboxSessionRequest):
    """
    Resume sandbox session (alias for /session endpoint with explicit intent).

    This endpoint uses the same intelligent retrieval as /session:
    - Checks all sources (memory, general cache, long-term cache, database)
    - Automatically resumes paused sandboxes
    - Reconnects to existing sandboxes
    - Creates new if sandbox doesn't exist anymore

    Note: Since get_sandbox() handles everything (reconnect, resume, create),
    this endpoint is functionally equivalent to /session. It exists for:
    - Semantic clarity (explicit "resume" intent)
    - Backward compatibility
    - Different response format

    For new integrations, prefer /session endpoint.

    Args:
        request: ResumeSandboxSessionRequest containing user_id and project_id

    Returns:
        ResumeSandboxSessionResponse with resume status
    """
    try:
        logger.info(
            f"Resuming sandbox for user={request.user_id}, project={request.project_id}"
        )

        # Use get_sandbox() - it handles everything!
        # (reconnect, resume, cache lookup, database fallback, create if needed)
        sandbox = await get_user_sandbox(request.user_id, request.project_id)

        logger.info(
            f"Sandbox {sandbox.sandbox_id} resumed/reconnected successfully for {request.user_id}/{request.project_id}"
        )

        return JSONResponse(
            status_code=200,
            content=ResumeSandboxSessionResponse(
                success=True,
                sandbox_id=sandbox.sandbox_id,
                resumed=True,
                message=f"Sandbox {sandbox.sandbox_id} ready (resumed/reconnected)",
            ).model_dump(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resume session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to resume session: {str(e)}"
        )


@router.post("/public-url", response_model=PublicURLResponse)
async def get_public_url(
    request: PublicURLRequest,
):
    """
    Get public URL for a specific port (3000 or 8000) on the sandbox.

    This endpoint will:
    - Get or reconnect to sandbox for user_id/project_id
    - Use sandbox.connect() to reconnect if necessary
    - Return public URL for the specified port

    Supported ports: 3000 (frontend), 8000 (backend)
    
    Example Request:
    ```
    {
        "user_id": "user_123",
        "project_id": "project_456",
        "port": 3000
    }
    ```
    """
    try:
        # Validate port
        if request.port not in [3000, 8000]:
            raise HTTPException(
                status_code=400,
                detail=f"Port {request.port} not supported. Only ports 3000 and 8000 are supported.",
            )

        logger.info(
            f"Getting public URL for port {request.port}, user={request.user_id}, project={request.project_id}"
        )

        # Get sandbox (this will reconnect if needed)
        sandbox = await get_user_sandbox(request.user_id, request.project_id)

        # Get public host for the port
        try:
            host = sandbox.get_host(request.port)
            public_url = f"https://{host}"

            logger.info(f"Public URL for port {request.port}: {public_url}")

            return JSONResponse(
                status_code=200,
                content=PublicURLResponse(
                    success=True,
                    sandbox_id=sandbox.sandbox_id,
                    port=request.port,
                    public_url=public_url,
                    message=f"Public URL retrieved successfully for port {request.port}",
                ).model_dump(),
            )

        except Exception as e:
            logger.error(f"Failed to get public URL for port {request.port}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get public URL for port {request.port}: {str(e)}",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get public URL: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get public URL: {str(e)}"
        )