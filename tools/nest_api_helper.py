"""
NestJS Backend API Helper
=========================

Routes all external API calls (Fal.ai, Brand.dev) through the NestJS backend
instead of calling them directly. This ensures:
- Credit management and tracking
- Consistent auth via internal service key
- S3 storage for generated assets
- Model validation and parameter defaults
"""

import os
import logging
from typing import Dict, Any, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# NestJS backend configuration
NEST_API_URL = os.getenv("NEST_API_URL", "http://localhost:4000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


def _get_headers(user_id: str) -> Dict[str, str]:
    """Build auth headers for internal service-to-service calls."""
    return {
        "Content-Type": "application/json",
        "X-Internal-Key": INTERNAL_API_KEY,
        "X-User-Id": user_id,
    }


def call_nest_api(
    method: str,
    path: str,
    json_body: Optional[Dict[str, Any]] = None,
    user_id: str = "",
    timeout: int = 300,
) -> Dict[str, Any]:
    """
    Call a NestJS backend endpoint with internal service auth.

    Args:
        method: HTTP method ("GET", "POST", etc.)
        path: Endpoint path (e.g., "/generation/text-to-image")
        json_body: JSON request body
        user_id: User ID to send via X-User-Id header
        timeout: Request timeout in seconds

    Returns:
        Dict with 'success' boolean and either 'data' or 'error'
    """
    if not INTERNAL_API_KEY:
        return {
            "success": False,
            "error": "INTERNAL_API_KEY not found in environment variables. "
                     "Set it in your .env file to enable NestJS integration.",
        }

    if not user_id:
        return {
            "success": False,
            "error": "user_id is required for NestJS API calls",
        }

    url = f"{NEST_API_URL}{path}"
    headers = _get_headers(user_id)

    try:
        with httpx.Client(timeout=timeout) as client:
            logger.info(f"NestJS API call: {method} {url}")

            response = client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
            )
            response.raise_for_status()
            data = response.json()

            return {
                "success": True,
                "data": data,
            }

    except httpx.HTTPStatusError as e:
        error_text = e.response.text
        status_code = e.response.status_code
        logger.error(f"NestJS API HTTP error: {status_code} - {error_text}")

        # Try to parse JSON error body from NestJS
        try:
            error_data = e.response.json()
            error_msg = error_data.get("message", error_text)
            if isinstance(error_msg, list):
                error_msg = "; ".join(error_msg)
        except Exception:
            error_msg = error_text

        return {
            "success": False,
            "error": f"HTTP {status_code}: {error_msg}",
        }

    except httpx.TimeoutException:
        logger.error(f"NestJS API timeout: {method} {url}")
        return {
            "success": False,
            "error": f"Request timed out after {timeout}s",
        }

    except httpx.ConnectError:
        logger.error(f"NestJS API connection error: {url}")
        return {
            "success": False,
            "error": f"Cannot connect to NestJS backend at {NEST_API_URL}. "
                     "Ensure the backend is running.",
        }

    except Exception as e:
        logger.error(f"NestJS API error: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
        }


async def call_nest_api_async(
    method: str,
    path: str,
    json_body: Optional[Dict[str, Any]] = None,
    user_id: str = "",
    timeout: int = 300,
) -> Dict[str, Any]:
    """
    Async version of call_nest_api for use in async tool functions.

    Args:
        method: HTTP method ("GET", "POST", etc.)
        path: Endpoint path (e.g., "/generation/text-to-image")
        json_body: JSON request body
        user_id: User ID to send via X-User-Id header
        timeout: Request timeout in seconds

    Returns:
        Dict with 'success' boolean and either 'data' or 'error'
    """
    if not INTERNAL_API_KEY:
        return {
            "success": False,
            "error": "INTERNAL_API_KEY not found in environment variables. "
                     "Set it in your .env file to enable NestJS integration.",
        }

    if not user_id:
        return {
            "success": False,
            "error": "user_id is required for NestJS API calls",
        }

    url = f"{NEST_API_URL}{path}"
    headers = _get_headers(user_id)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            logger.info(f"NestJS API call (async): {method} {url}")

            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
            )
            response.raise_for_status()
            data = response.json()

            return {
                "success": True,
                "data": data,
            }

    except httpx.HTTPStatusError as e:
        error_text = e.response.text
        status_code = e.response.status_code
        logger.error(f"NestJS API HTTP error: {status_code} - {error_text}")

        try:
            error_data = e.response.json()
            error_msg = error_data.get("message", error_text)
            if isinstance(error_msg, list):
                error_msg = "; ".join(error_msg)
        except Exception:
            error_msg = error_text

        return {
            "success": False,
            "error": f"HTTP {status_code}: {error_msg}",
        }

    except httpx.TimeoutException:
        logger.error(f"NestJS API timeout: {method} {url}")
        return {
            "success": False,
            "error": f"Request timed out after {timeout}s",
        }

    except httpx.ConnectError:
        logger.error(f"NestJS API connection error: {url}")
        return {
            "success": False,
            "error": f"Cannot connect to NestJS backend at {NEST_API_URL}. "
                     "Ensure the backend is running.",
        }

    except Exception as e:
        logger.error(f"NestJS API error: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
        }
