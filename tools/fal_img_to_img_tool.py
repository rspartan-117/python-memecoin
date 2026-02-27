"""
Fal.ai Image-to-Image Tool
==========================

Transform existing images based on text prompts using Fal.ai models.
Routes through NestJS backend for credit management and model validation.
"""

import json
import logging
from langchain.tools import tool, ToolRuntime

from context.runtime_context import RuntimeContext, get_runtime_context
from agent_state import LandingPageAgentState
from tools.nest_api_helper import call_nest_api_async

logger = logging.getLogger(__name__)


@tool
async def generate_image_img_to_img(
    image_url: str,
    prompt: str,
    model: str = "fal-ai/nano-banana/edit",
    strength: float = 0.95,
    image_size: str = "landscape_4_3",
    num_images: int = 1,
    enable_safety_checker: bool = True,
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState] = None,
) -> str:
    """
    Transform existing images based on text prompts using Fal.ai models.
    
    Takes an existing image and modifies it according to your text description.
    Great for variations, style transfers, and iterative refinement of game assets.
    
    Args:
        image_url: URL of the source image to transform (must be publicly accessible)
        
        prompt: Text description of how to transform the image.
               Example: "Make this character look more cyberpunk with neon accents"
        
        strength: How much to change the image (0.0-1.0):
                 - 0.0-0.3: Very subtle changes, preserve most details
                 - 0.4-0.7: Moderate changes, good for style adjustments
                 - 0.8-1.0: Major changes, can significantly alter the image
                 Default: 0.95 (strong transformation)
        
        model: AI model to use:
               - "fal-ai/nano-banana/edit" (default) - Good for transformations
               - "fal-ai/nano-banana-pro/edit" - Premium quality
               - "fal-ai/flux-2/edit" - Best quality for professional work
               
        image_size: Output image aspect ratio (same options as text_to_image)
        num_images: Number of variations to generate (1-4)
        enable_safety_checker: Filter inappropriate content (default: True)
        
    Returns:
        JSON string with transformed image URLs and metadata.
        
    Examples:
        # Apply style transfer to game asset
        generate_image_img_to_img(
            image_url="https://example.com/sword.png",
            prompt="Convert to pixel art style, 16-bit retro gaming aesthetic",
            strength=0.8
        )
        
        # Subtle variation of character
        generate_image_img_to_img(
            image_url="https://example.com/character.png",
            prompt="Change armor color to blue and gold",
            strength=0.4
        )
        
        # Major transformation
        generate_image_img_to_img(
            image_url="https://example.com/landscape.png",
            prompt="Transform to night time with moonlight and stars",
            strength=0.95,
            num_images=2
        )
    
    Use Cases:
        - Style transfer for consistency across assets
        - Iterative refinement of generated images
        - Color palette adjustments
        - Adding or removing elements
        - Changing lighting and atmosphere
        - Creating variations of existing assets
    """
    if not image_url or not image_url.strip():
        return json.dumps({
            "success": False,
            "error": "image_url cannot be empty"
        })
    
    if not prompt or not prompt.strip():
        return json.dumps({
            "success": False,
            "error": "prompt cannot be empty"
        })
    
    # Validate strength
    if strength < 0.0 or strength > 1.0:
        return json.dumps({
            "success": False,
            "error": "strength must be between 0.0 and 1.0"
        })
    
    # Validate num_images
    if num_images < 1 or num_images > 4:
        return json.dumps({
            "success": False,
            "error": "num_images must be between 1 and 4"
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
        f"Transforming image via NestJS: model={model}, image_url={image_url[:50]}..., "
        f"prompt='{prompt[:50]}...', strength={strength}"
    )
    
    # Build NestJS-compatible request body
    # NestJS expects: { modelName, params: { prompt, image_urls: [...], ... }, waitForCompletion, timeoutMs }
    # Note: NestJS uses image_urls (array) not image_url (single string)
    request_body = {
        "modelName": model,
        "params": {
            "prompt": prompt.strip(),
            "image_urls": [image_url.strip()],
            "image_size": image_size,
            "num_images": num_images,
            "enable_safety_checker": enable_safety_checker,
        },
        "waitForCompletion": True,
        "timeoutMs": 300000,
    }
    
    # Call NestJS generation endpoint
    result = await call_nest_api_async(
        method="POST",
        path="/generation/image-to-image",
        json_body=request_body,
        user_id=user_id,
        timeout=300,
    )
    
    if not result.get("success"):
        return json.dumps({
            "success": False,
            "error": result.get("error", "Unknown error"),
        })
    
    # Format successful response from NestJS
    data = result.get("data", {})
    
    # NestJS returns: { success, assetId, imageUrl, creditsUsed, creditsRemaining, model, metadata }
    metadata = data.get("metadata", {})
    result_image_url = data.get("imageUrl", "")
    
    response = {
        "success": True,
        "model": model,
        "prompt": prompt,
        "source_image": image_url,
        "strength": strength,
        "num_images": 1,
        "images": [
            {
                "url": result_image_url,
                "width": metadata.get("width"),
                "height": metadata.get("height"),
                "content_type": f"image/{metadata.get('format', 'webp')}"
            }
        ] if result_image_url else [],
        "seed": metadata.get("seed"),
        "credits_used": data.get("creditsUsed"),
        "credits_remaining": data.get("creditsRemaining"),
        "asset_id": data.get("assetId"),
        "message": f"Successfully transformed image" if result_image_url else "Transformation returned no image"
    }
    
    return json.dumps(response, indent=2)
