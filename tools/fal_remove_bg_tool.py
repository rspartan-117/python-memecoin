"""
Fal.ai Background Removal Tool
==============================

Remove backgrounds from images to create transparent PNGs.
Routes through NestJS backend for credit management.
"""

import json
import logging
from langchain.tools import tool, ToolRuntime

from context.runtime_context import RuntimeContext, get_runtime_context
from agent_state import LandingPageAgentState
from tools.nest_api_helper import call_nest_api_async

logger = logging.getLogger(__name__)


@tool
async def remove_background_from_image(
    image_url: str,
    crop_to_bbox: bool = False,
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState] = None,
) -> str:
    """
    Remove background from images to create transparent PNG files.
    
    Perfect for creating clean game assets, character sprites, UI elements,
    and product images with transparent backgrounds.
    
    Args:
        image_url: URL of the image to process (must be publicly accessible)
                  Supports common formats: JPG, PNG, WebP
        
        crop_to_bbox: Whether to crop the result to the foreground object's 
                     bounding box, removing extra transparent space.
                     - True: Tight crop around object (good for sprites)
                     - False: Keep original dimensions (default)
        
    Returns:
        JSON string with the processed image URL (transparent PNG) and metadata.
        
    Examples:
        # Remove background from character art
        remove_background_from_image(
            image_url="https://example.com/character.jpg"
        )
        
        # Remove background and crop to object for sprite
        remove_background_from_image(
            image_url="https://example.com/item.png",
            crop_to_bbox=True
        )
        
        # Process UI element
        remove_background_from_image(
            image_url="https://example.com/button.jpg",
            crop_to_bbox=False
        )
    
    Use Cases:
        - Character sprites and game objects
        - UI elements and icons
        - Item and weapon assets
        - Avatar and profile images
        - Extracting objects from photos
        - Creating layered compositions
        - Preparing assets for game engines
        
    Note:
        - Output is always PNG format with alpha channel
        - Processing typically takes 10-30 seconds
        - Works best with clear foreground subjects
        - May not work well on complex or abstract images
    """
    if not image_url or not image_url.strip():
        return json.dumps({
            "success": False,
            "error": "image_url cannot be empty"
        })
    
    # Get user_id from runtime context
    try:
        ctx = get_runtime_context()
        user_id = ctx.user_id
    except Exception:
        user_id = ""
    
    if not user_id:
        return json.dumps({
            "success": False,
            "error": "No user context available. Cannot authenticate with backend."
        })
    
    logger.info(
        f"Removing background via NestJS: image_url={image_url[:50]}..., "
        f"crop_to_bbox={crop_to_bbox}"
    )
    
    # Build NestJS-compatible request body
    # NestJS BackgroundRemovalWithCreditsDto: { image_url, crop_to_bbox, waitForCompletion, timeoutMs }
    request_body = {
        "image_url": image_url.strip(),
        "crop_to_bbox": crop_to_bbox,
        "waitForCompletion": True,
        "timeoutMs": 120000,
    }
    
    # Call NestJS background removal endpoint
    result = await call_nest_api_async(
        method="POST",
        path="/generation/remove-background",
        json_body=request_body,
        user_id=user_id,
        timeout=120,
    )
    
    if not result.get("success"):
        return json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error"),
        })
    
    # Format successful response from NestJS
    data = result.get("data", {})
    metadata = data.get("metadata", {})
    
    response = {
        "success": True,
        "model": data.get("model", "fal-ai/imageutils/rembg"),
        "source_image": image_url,
        "crop_to_bbox": crop_to_bbox,
        "result": {
            "url": data.get("imageUrl"),
            "width": metadata.get("width"),
            "height": metadata.get("height"),
            "content_type": "image/png"
        },
        "credits_used": data.get("creditsUsed"),
        "credits_remaining": data.get("creditsRemaining"),
        "asset_id": data.get("assetId"),
        "message": "Successfully removed background and created transparent PNG"
    }
    
    return json.dumps(response, indent=2)
