"""
Fal.ai Text-to-Image Tool
=========================

Generate images from text prompts using Fal.ai models.
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
async def generate_image_text_to_image(
    prompt: str,
    model: str = "fal-ai/flux-2/dev",
    image_size: str = "landscape_4_3",
    num_images: int = 1,
    enable_safety_checker: bool = True,
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState] = None,
) -> str:
    """
    Generate images from text prompts using Fal.ai models.
    
    Creates high-quality images based on text descriptions. Perfect for generating
    game assets, concept art, UI elements, character designs, and more.
    
    Args:
        prompt: Detailed text description of the image you want to generate.
               Be specific about style, colors, composition, and details.
               Example: "A futuristic sci-fi spaceship with glowing blue engines,
                        metallic hull, flying through a nebula, digital art style"
        
        model: AI model to use. Options:
               - "fal-ai/flux/schnell" (default) - Fast, high quality, good for most needs
               - "fal-ai/flux-2/dev" - Higher quality, slower
               - "fal-ai/nano-banana" - Fast generation with aspect ratio control
               - "fal-ai/nano-banana-pro" - Premium quality with resolution options
               
        image_size: Aspect ratio of generated image. Options:
                   - "square_hd" (1024x1024)
                   - "square" (512x512)
                   - "portrait_4_3" (768x1024)
                   - "portrait_16_9" (576x1024)
                   - "landscape_4_3" (1024x768) - default
                   - "landscape_16_9" (1024x576)
                   
        num_images: How many variations to generate (1-4, default: 1)
        
        enable_safety_checker: Filter inappropriate content (default: True)
        
    Returns:
        JSON string with generation results including image URLs and metadata.
        
    Examples:
        # Generate game character concept art
        generate_image_text_to_image(
            prompt="A heroic knight in shining armor with a magical sword, 
                   fantasy art style, detailed, epic lighting",
            image_size="portrait_4_3"
        )
        
        # Generate UI background
        generate_image_text_to_image(
            prompt="Abstract geometric pattern in blue and purple, 
                   minimalist, clean lines, modern UI background",
            image_size="landscape_16_9",
            model="fal-ai/flux/schnell"
        )
        
        # Generate multiple game asset variations
        generate_image_text_to_image(
            prompt="A wooden treasure chest with gold trim, isometric view, 
                   game asset, clean background",
            num_images=3
        )
    
    Use Cases:
        - Game character and creature designs
        - Environment and landscape concept art
        - UI backgrounds and textures
        - Item and weapon designs
        - Logo and icon generation
        - Scene composition and layouts
    """
    if not prompt or not prompt.strip():
        return json.dumps({
            "success": False,
            "error": "Prompt cannot be empty"
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
        f"Generating image via NestJS: model={model}, prompt='{prompt[:50]}...', "
        f"size={image_size}, num_images={num_images}"
    )
    
    # Build NestJS-compatible request body
    # NestJS expects: { modelName, params: { prompt, image_size, ... }, waitForCompletion, timeoutMs }
    request_body = {
        "modelName": model,
        "params": {
            "prompt": prompt.strip(),
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
        path="/generation/text-to-image",
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
    image_url = data.get("imageUrl", "")
    
    response = {
        "success": True,
        "model": model,
        "prompt": prompt,
        "image_size": image_size,
        "num_images": 1,
        "images": [
            {
                "url": image_url,
                "width": metadata.get("width"),
                "height": metadata.get("height"),
                "content_type": f"image/{metadata.get('format', 'webp')}"
            }
        ] if image_url else [],
        "seed": metadata.get("seed"),
        "credits_used": data.get("creditsUsed"),
        "credits_remaining": data.get("creditsRemaining"),
        "asset_id": data.get("assetId"),
        "message": f"Successfully generated image" if image_url else "Generation returned no image"
    }
    
    return json.dumps(response, indent=2)
