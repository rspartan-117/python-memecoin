"""
Fal.ai API Helper Functions
============================

Shared utilities for Fal.ai API integration.
"""

import os
import logging
from typing import Dict, Any
import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Fal.ai API configuration
FAL_API_KEY = os.getenv("FAL_API_KEY")
FAL_API_BASE = "https://queue.fal.run"


def call_fal_api(
    model_name: str,
    input_params: Dict[str, Any],
    timeout: int = 300,
) -> Dict[str, Any]:
    """
    Call Fal.ai API with polling for completion.
    
    Args:
        model_name: Fal.ai model name (e.g., "fal-ai/flux/schnell")
        input_params: Model input parameters
        timeout: Maximum wait time in seconds
        
    Returns:
        Dict with 'success' boolean and either 'data' or 'error'
    """
    if not FAL_API_KEY:
        return {
            "success": False,
            "error": "FAL_API_KEY not found in environment variables"
        }
    
    headers = {
        "Authorization": f"Key {FAL_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        # Submit generation request
        with httpx.Client(timeout=timeout) as client:
            submit_url = f"{FAL_API_BASE}/{model_name}"
            logger.info(f"Submitting to Fal.ai: {model_name}")
            
            response = client.post(
                submit_url,
                headers=headers,
                json=input_params
            )
            response.raise_for_status()
            result = response.json()
            
            # Check if we need to poll or if result is immediate
            if "request_id" in result:
                # Poll for result
                request_id = result["request_id"]
                status_url = f"{FAL_API_BASE}/{model_name}/requests/{request_id}/status"
                
                logger.info(f"Polling for completion: request_id={request_id}")
                
                import time
                max_attempts = timeout // 2  # Poll every 2 seconds
                for attempt in range(max_attempts):
                    time.sleep(2)
                    
                    status_response = client.get(status_url, headers=headers)
                    status_response.raise_for_status()
                    status_data = status_response.json()
                    
                    if status_data.get("status") == "COMPLETED":
                        # Get final result
                        result_url = f"{FAL_API_BASE}/{model_name}/requests/{request_id}"
                        final_response = client.get(result_url, headers=headers)
                        final_response.raise_for_status()
                        return {
                            "success": True,
                            "data": final_response.json()
                        }
                    elif status_data.get("status") == "FAILED":
                        error_msg = status_data.get("error", "Unknown error")
                        return {
                            "success": False,
                            "error": f"Generation failed: {error_msg}"
                        }
                
                return {
                    "success": False,
                    "error": f"Request timed out after {timeout}s"
                }
            else:
                # Immediate result
                return {
                    "success": True,
                    "data": result
                }
                
    except httpx.HTTPStatusError as e:
        logger.error(f"Fal.ai API HTTP error: {e}")
        return {
            "success": False,
            "error": f"HTTP error: {e.response.status_code} - {e.response.text}"
        }
    except Exception as e:
        logger.error(f"Fal.ai API error: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }
