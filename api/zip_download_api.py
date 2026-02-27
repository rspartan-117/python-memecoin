"""
Landing Page Project ZIP Download API
==========================

Single unified endpoint for all ZIP download scenarios.
Based on optimized ZipDownloadService with universal create_zip() method.

Supported Templates:
- Primary: meme-coin-base-v0 (/home/user/project) - Landing page generation (current)
- Legacy: game-gen-pre-v1 (/home/user/game) - Game projects
- Legacy: react-fast-mongo-pre-v0 (/home/user/code) - Fullstack projects
- Auto-detects template and base directory

Features:
- One endpoint for all use cases (full project, folders, assets, custom paths)
- Direct download URL generation (no streaming)
- Support for E2B signed URLs with expiration
- Smart parameter handling (relative/absolute paths)
- Production-ready error handling

Endpoint:
- POST /api/projects/{project_id}/download - Universal download endpoint
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Body, Query
from pydantic import BaseModel, Field, field_validator

from services.zip_download_service import get_zip_service

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/projects", tags=["downloads"])


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class DownloadRequest(BaseModel):
    """
    Request model for downloading a ZIP archive of the landing page project from E2B sandbox.

    ## How It Works
    1. The service connects to the user's E2B sandbox (identified by user_id + project_id)
    2. Auto-detects the project directory based on sandbox template:
       - **meme-coin-base-v0** → `/home/user/project/` (current primary template)
       - **game-gen-pre-v1** → `/home/user/game/` (legacy)
       - **react-fast-mongo-pre-v0** → `/home/user/code/` (legacy)
    3. Creates a ZIP archive of the full project folder (or a subfolder if specified)
    4. Returns a signed download URL that expires after the configured time

    ## Quick Start
    Most common usage is to download the entire project — just provide `user_id` and `project_id`:
    ```json
    {
        "user_id": "user_123",
        "project_id": "project_456"
    }
    ```

    ## Sandbox Structure (meme-coin-base-v0)
    The current template has this layout at `/home/user/project/`:
    ```
    /home/user/project/
    ├── index.html          ← Main landing page (entry point)
    ├── style.css           ← Styles (optional)
    ├── script.js           ← Pre-installed error logger
    ├── background.webp     ← Default background image
    └── fonts/              ← Custom fonts (Cuba, Tomato Grotesk)
    ```

    ## Important Notes
    - Only **folders** can be zipped, not individual files
    - The sandbox must have `zip` utility installed (template requirement)
    - Download URLs are signed and expire (default: ~2.7 hours)
    """

    user_id: str = Field(
        ...,
        description=(
            "Unique user identifier. Used together with project_id to locate "
            "the user's E2B sandbox session."
        ),
        example="user_123",
        json_schema_extra={"title": "User ID"},
    )
    project_id: str = Field(
        ...,
        description=(
            "Unique project identifier. Maps to the sandbox session containing "
            "the user's landing page files. This is the same project_id used in /chat."
        ),
        example="project_456",
        json_schema_extra={"title": "Project ID"},
    )

    source_path: Optional[str] = Field(
        None,
        description=(
            "**Folder path to include in the ZIP archive.**\n\n"
            "- `null` (default) → Zips the **entire project folder** (recommended for most cases)\n"
            "- Relative path (e.g., `fonts`) → Zips a subfolder relative to the auto-detected base directory\n"
            "- Absolute path (e.g., `/home/user/project/fonts`) → Zips the exact folder specified\n\n"
            "**Only folders are supported.** Do not pass individual file paths like `index.html`.\n\n"
            "**Auto-detected base directories by template:**\n"
            "- meme-coin-base-v0 → `/home/user/project/`\n"
            "- game-gen-pre-v1 → `/home/user/game/`\n"
            "- react-fast-mongo-pre-v0 → `/home/user/code/`"
        ),
        example=None,
        json_schema_extra={"title": "Source Folder Path"},
    )

    zip_name: Optional[str] = Field(
        None,
        description=(
            "Custom filename for the ZIP archive. If not provided, a name is auto-generated "
            "in the format: `project_{project_id}_{timestamp}.zip`. "
            "The `.zip` extension is appended automatically if missing."
        ),
        example="my_landing_page.zip",
        json_schema_extra={"title": "ZIP Filename"},
    )

    exclude_patterns: Optional[List[str]] = Field(
        None,
        description=(
            "Additional glob patterns for files/folders to exclude from the ZIP. "
            "These are passed as `-x` arguments to the `zip` command.\n\n"
            "If `use_defaults` is True (default), these patterns are **merged** with built-in defaults "
            "(node_modules, .git, __pycache__, *.log, *.zip, etc.).\n\n"
            "If `use_defaults` is False, **only** these patterns are used for exclusion."
        ),
        example=["*.log", "*.tmp"],
        json_schema_extra={"title": "Exclude Patterns"},
    )

    use_defaults: bool = Field(
        True,
        description=(
            "Whether to include the built-in default exclusion patterns.\n\n"
            "**Default excludes include:** `node_modules`, `.git`, `__pycache__`, `*.pyc`, "
            "`.DS_Store`, `dist`, `build`, `*.log`, `*.zip`, and system directories.\n\n"
            "Set to `false` only if you want complete control over what gets excluded."
        ),
        json_schema_extra={"title": "Use Default Excludes"},
    )

    url_expiration: Optional[int] = Field(
        None,
        description=(
            "Download URL expiration time in **seconds**. After this time, the signed URL becomes invalid.\n\n"
            "- Default: `10000` seconds (~2.7 hours)\n"
            "- Example: `3600` = 1 hour\n"
            "- Example: `86400` = 24 hours\n\n"
            "The URL is an E2B signed URL pointing to the ZIP file stored in the sandbox."
        ),
        example=3600,
        json_schema_extra={"title": "URL Expiration (seconds)"},
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Full Project Download (Recommended)",
                    "description": "Downloads the entire /home/user/project/ folder as a ZIP",
                    "value": {
                        "user_id": "user_123",
                        "project_id": "project_456",
                    },
                },
                {
                    "summary": "Download with Custom ZIP Name",
                    "description": "Full project download with a custom filename",
                    "value": {
                        "user_id": "user_123",
                        "project_id": "project_456",
                        "zip_name": "my_landing_page.zip",
                    },
                },
                {
                    "summary": "Download Fonts Subfolder",
                    "description": "Zip only the fonts/ subfolder from the project",
                    "value": {
                        "user_id": "user_123",
                        "project_id": "project_456",
                        "source_path": "fonts",
                    },
                },
                {
                    "summary": "Download with Custom Expiration",
                    "description": "Full project with 1-hour URL expiration",
                    "value": {
                        "user_id": "user_123",
                        "project_id": "project_456",
                        "url_expiration": 3600,
                    },
                },
                {
                    "summary": "Download with Absolute Path (Legacy)",
                    "description": "Use absolute path for older deployed ZIP service",
                    "value": {
                        "user_id": "user_123",
                        "project_id": "project_456",
                        "source_path": "/home/user/project",
                    },
                },
            ]
        }
    }

    @field_validator("source_path", mode="before")
    @classmethod
    def normalize_source_path(cls, v):
        """Convert empty string to None for consistent handling."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class DownloadResponse(BaseModel):
    """Response model returned after successful ZIP creation. Contains the signed download URL and metadata."""

    success: bool = Field(..., description="Whether the ZIP was created successfully")

    download_url: str = Field(
        ...,
        description=(
            "Signed download URL for the ZIP file. This is an E2B sandbox URL with authentication signature. "
            "Open this URL in a browser or use it with wget/curl to download the ZIP. "
            "The URL expires after the configured expiration time."
        ),
    )

    filename: str = Field(
        ..., description="Name of the generated ZIP file (e.g., 'project_project_456_20260226_133000.zip')"
    )

    source_path: str = Field(
        ..., description="The folder path that was zipped (e.g., '/home/user/project' or '/home/user/project/fonts')"
    )

    is_full_project: bool = Field(
        ..., description="True if the entire project folder was zipped (source_path was null)"
    )

    size_bytes: int = Field(..., description="ZIP file size in bytes")

    size_mb: float = Field(..., description="ZIP file size in megabytes (rounded to 2 decimals)")

    created_at: str = Field(..., description="ISO 8601 timestamp when the ZIP was created")

    expires_at: str = Field(
        ..., description="ISO 8601 timestamp when the download URL expires and becomes invalid"
    )

    sandbox_path: str = Field(
        ...,
        description="Full path to the ZIP file inside the E2B sandbox (useful for debugging or cleanup)",
    )

    user_id: str = Field(..., description="User ID from the request")
    project_id: str = Field(..., description="Project ID from the request")


class ListZipsRequest(BaseModel):
    """Request model for listing ZIP files"""

    user_id: str = Field(..., description="User identifier", example="user_123")
    project_id: str = Field(
        ..., description="Project identifier", example="project_456"
    )


class CleanupRequest(BaseModel):
    """Request model for cleaning up ZIP files"""

    user_id: str = Field(..., description="User identifier", example="user_123")
    project_id: str = Field(
        ..., description="Project identifier", example="project_456"
    )
    sandbox_path: Optional[str] = Field(
        None, description="Specific ZIP path to delete (None = delete all)"
    )


# =============================================================================
# UNIVERSAL DOWNLOAD ENDPOINT
# =============================================================================


@router.post(
    "/download",
    response_model=DownloadResponse,
    summary="Download Project as ZIP",
    description=(
        "## ZIP Download for Landing Page Projects\n\n"
        "Creates a ZIP archive of the user's landing page project from the E2B sandbox "
        "and returns a signed download URL.\n\n"
        "### How to Use\n"
        "1. Send a POST request with `user_id` and `project_id`\n"
        "2. The service locates the user's active sandbox session\n"
        "3. It auto-detects the project directory (`/home/user/project/` for meme-coin-base-v0)\n"
        "4. Creates a ZIP of the entire folder (or a subfolder if `source_path` is set)\n"
        "5. Returns a signed download URL you can open in a browser\n\n"
        "### Supported Templates\n"
        "| Template | Project Directory |\n"
        "|---|---|\n"
        "| **meme-coin-base-v0** (current) | `/home/user/project/` |\n"
        "| game-gen-pre-v1 (legacy) | `/home/user/game/` |\n"
        "| react-fast-mongo-pre-v0 (legacy) | `/home/user/code/` |\n\n"
        "### Prerequisites\n"
        "- User must have an active sandbox (created via /chat endpoint)\n"
        "- Sandbox template must have `zip` utility installed\n\n"
        "### Error Codes\n"
        "- **400** - Invalid request parameters\n"
        "- **404** - Folder not found in sandbox\n"
        "- **403** - Permission denied\n"
        "- **500** - ZIP creation failed or sandbox connection error"
    ),
)
async def download_project_zip(
    request: DownloadRequest = Body(...),
) -> DownloadResponse:
    """
    Project ZIP download endpoint - zips entire project or a subfolder.

    Use Cases:
    1. Full project: source_path=None (entire project directory)
    2. Subfolder: source_path="fonts" or source_path="assets"
    3. Absolute folder: source_path="/home/user/project/fonts"

    Note: Only folders are supported, not individual files.

    Args:
        request: DownloadRequest with download parameters including project_id

    Returns:
        DownloadResponse with download_url and metadata

    Raises:
        HTTPException 400: Invalid path or parameters
        HTTPException 404: Path not found in sandbox
        HTTPException 500: ZIP creation or sandbox error

    Example Requests:

    ```
    # Full landing page project (recommended)
    {
        "user_id": "user_123",
        "project_id": "project_456"
    }

    # Subfolder (e.g., fonts)
    {
        "user_id": "user_123",
        "project_id": "project_456",
        "source_path": "fonts"
    }

    # Custom excludes (exclude logs)
    {
        "user_id": "user_123",
        "project_id": "project_456",
        "source_path": null,
        "exclude_patterns": ["*.log"],
        "use_defaults": true
    }

    # Custom expiration (1 hour)
    {
        "user_id": "user_123",
        "project_id": "project_456",
        "url_expiration": 3600
    }
    ```
    """

    try:
        # Log request
        source_desc = request.source_path or "full project"
        logger.info(
            f"[{request.user_id}/{request.project_id}] Download request: {source_desc}"
        )

        # Get service instance
        service = get_zip_service()

        # Call universal create_zip method
        result = await service.create_zip(
            user_id=request.user_id,
            project_id=request.project_id,
            source_path=request.source_path,
            zip_name=request.zip_name,
            exclude_patterns=request.exclude_patterns,
            use_defaults=request.use_defaults,
            url_expiration=request.url_expiration,
        )

        # Log success
        logger.info(
            f"[{request.user_id}/{request.project_id}] ZIP created: "
            f"{result['filename']} ({result['size_mb']} MB)"
        )

        # Return response
        return DownloadResponse(**result)

    except ValueError as e:
        # Invalid parameters
        logger.warning(f"Invalid download request: {e}")
        raise HTTPException(
            status_code=400, detail=f"Invalid request parameters: {str(e)}"
        )

    except FileNotFoundError as e:
        # Path not found
        logger.warning(f"Path not found: {e}")
        raise HTTPException(
            status_code=404, detail=f"Path not found in sandbox: {str(e)}"
        )

    except Exception as e:
        # General error (sandbox issues, ZIP creation failed, etc.)
        error_msg = str(e)
        logger.error(
            f"[{request.user_id}/{request.project_id}] Download error: {error_msg}",
            exc_info=True,
        )

        # Check for specific error types
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=404, detail=f"Resource not found: {error_msg}"
            )
        elif "permission" in error_msg.lower():
            raise HTTPException(
                status_code=403, detail=f"Permission denied: {error_msg}"
            )
        else:
            raise HTTPException(
                status_code=500, detail=f"Failed to create ZIP: {error_msg}"
            )


# =============================================================================
# UTILITY ENDPOINTS
# =============================================================================


@router.post(
    "/list-zips",
    summary="List ZIP Files",
    description="List all existing ZIP files in the sandbox",
)
async def list_project_zips(
    request: ListZipsRequest = Body(...),
):
    """
    List all ZIP files in base directory (auto-detected: /home/user/game or /home/user/code).

    Args:
        request: ListZipsRequest with user_id and project_id

    Returns:
        List of ZIP files with metadata
    """
    try:
        logger.info(f"[{request.user_id}/{request.project_id}] Listing ZIP files")

        service = get_zip_service()
        zip_files = await service.list_zip_files(request.user_id, request.project_id)

        return {
            "success": True,
            "project_id": request.project_id,
            "zip_count": len(zip_files),
            "zip_files": zip_files,
        }

    except Exception as e:
        logger.error(f"Error listing ZIPs: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to list ZIP files: {str(e)}"
        )


@router.post(
    "/cleanup",
    summary="Cleanup ZIP Files",
    description="Delete specific or all ZIP files to free sandbox space",
)
async def cleanup_project_zips(
    request: CleanupRequest = Body(...),
):
    """
    Cleanup ZIP files in sandbox.

    Args:
        request: CleanupRequest with user_id, project_id, and optional sandbox_path

    Returns:
        Cleanup status
    """
    try:
        service = get_zip_service()

        if request.sandbox_path:
            # Delete specific ZIP
            logger.info(
                f"[{request.user_id}/{request.project_id}] Deleting: {request.sandbox_path}"
            )
            success = await service.cleanup_zip(
                request.user_id, request.project_id, request.sandbox_path
            )

            return {
                "success": success,
                "message": "ZIP file deleted" if success else "Delete failed",
                "deleted_path": request.sandbox_path,
            }
        else:
            # Delete all ZIPs
            logger.info(
                f"[{request.user_id}/{request.project_id}] Cleaning up all ZIPs"
            )
            zip_files = await service.list_zip_files(
                request.user_id, request.project_id
            )

            deleted_count = 0
            for zf in zip_files:
                success = await service.cleanup_zip(
                    request.user_id, request.project_id, zf["path"]
                )
                if success:
                    deleted_count += 1

            return {
                "success": True,
                "message": f"Deleted {deleted_count} ZIP files",
                "deleted_count": deleted_count,
                "total_count": len(zip_files),
            }

    except Exception as e:
        logger.error(f"Error during cleanup: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to cleanup ZIPs: {str(e)}")


# @router.get(
#     "/{project_id}/download/info",
#     summary="Get ZIP Info",
#     description="Get information about a specific ZIP file",
# )
# async def get_zip_file_info(
#     project_id: str,
#     user_id: str,
#     sandbox_path: str,
# ):
#     """
#     Get metadata about a specific ZIP file.

#     Args:
#         project_id: Project identifier
#         user_id: User identifier (query parameter)
#         sandbox_path: Full path to ZIP file in sandbox

#     Returns:
#         ZIP file metadata or 404 if not found
#     """
#     try:
#         logger.info(f"[{user_id}/{project_id}] Getting info: {sandbox_path}")

#         service = get_zip_service()
#         info = await service.get_zip_info(user_id, project_id, sandbox_path)

#         if not info:
#             raise HTTPException(
#                 status_code=404, detail=f"ZIP file not found: {sandbox_path}"
#             )

#         return {
#             "success": True,
#             "project_id": project_id,
#             "zip_info": info,
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error getting ZIP info: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail=f"Failed to get ZIP info: {str(e)}")


# =============================================================================
# INTEGRATION HELPER
# =============================================================================


def include_download_routes(app):
    """
    Include download routes in the main FastAPI app.

    Usage:
        from api.zip_download_api import include_download_routes

        app = FastAPI()
        include_download_routes(app)
    """
    app.include_router(router)
    logger.info("Universal ZIP download routes registered")
