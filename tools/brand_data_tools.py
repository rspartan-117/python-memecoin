"""
Brand.dev Data Tools for LangGraph
==================================

Tools for retrieving brand assets (logos, colors, fonts) and AI-powered
data extraction from company websites.

Routes all requests through the NestJS backend which handles:
- Brand.dev SDK integration and caching
- API key management
- Error handling and retries
"""

import os
import json
import logging
from typing import Optional, Dict, Any
from langchain.tools import tool, ToolRuntime
from dotenv import load_dotenv

from context.runtime_context import RuntimeContext, get_runtime_context
from agent_state import LandingPageAgentState
from tools.nest_api_helper import call_nest_api_async

load_dotenv()
logger = logging.getLogger(__name__)


@tool
async def get_brand_data(
    domain: str,
    force_refresh: bool = False,
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState] = None,
) -> str:
    """
    Retrieve comprehensive brand data for a company domain using Brand.dev API.
    
    Fetches brand assets including logos, colors, fonts, descriptions, and social links.
    Results are cached for 1 hour to improve performance and reduce API calls.
    
    Args:
        domain: Company domain or website URL.
               Examples: "uniswap.org", "https://nike.com", "www.apple.com"
               Will be automatically normalized (protocol and www removed)
        
        force_refresh: Bypass cache and fetch fresh data from API (default: False)
                      Use when you need the most up-to-date brand information
        
    Returns:
        JSON string with brand data including:
        - title: Company name
        - description: Company description
        - logos: Array of logo URLs in various sizes and formats
        - colors: Array of brand colors with hex codes and names
        - fonts: Array of brand fonts with names and weights
        - links: Social media and other important links
        - cached: Whether this data came from cache
        
    Examples:
        # Get brand data for a company
        get_brand_data(domain="uniswap.org")
        
        # Force fresh data from API
        get_brand_data(domain="https://www.nike.com", force_refresh=True)
        
        # Use for theming a game UI
        get_brand_data(domain="spotify.com")
    
    Use Cases:
        - Theming game UI based on brand colors
        - Fetching company logos for integrations
        - Getting brand guidelines for custom implementations
        - Extracting color palettes for game design
        - Finding official fonts for text elements
        - Gathering social media links for sharing features
        
    Note:
        - Requires BRAND_DEV_API_KEY in environment variables
        - Results cached for 1 hour (3600 seconds)
        - Cache can be bypassed with force_refresh=True
        - Normalized domains used as cache keys
    """
    if not domain or not domain.strip():
        return json.dumps({
            "success": False,
            "error": "Domain cannot be empty"
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
    
    logger.info(f"Fetching brand data via NestJS: domain={domain}, user_id={user_id}")
    
    # Call NestJS POST /brand/retrieve
    result = await call_nest_api_async(
        method="POST",
        path="/brand/retrieve",
        json_body={
            "domain": domain.strip(),
            "forceRefresh": force_refresh,
        },
        user_id=user_id,
        timeout=30,
    )
    
    if not result.get("success"):
        error_msg = result.get("error", "Unknown error")
        logger.error(f"Brand data fetch failed: {error_msg}")
        return json.dumps({
            "success": False,
            "error": error_msg,
            "domain": domain,
        })
    
    # Return the NestJS response data directly
    data = result.get("data", {})
    
    # Ensure standard response format
    if isinstance(data, dict):
        data["success"] = True
        data["domain"] = domain.strip()
    
    return json.dumps(data, indent=2, default=str)


@tool
async def ai_query_brand_website(
    domain: str,
    query: str,
    max_speed: bool = False,
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState] = None,
) -> str:
    """
    Extract custom data from any website using AI-powered natural language queries.
    
    Ask questions about a company's website and get AI-extracted answers.
    Great for gathering specific information not available in standard brand data.
    
    Args:
        domain: Company domain or website URL to query.
               Examples: "stripe.com", "https://openai.com"
               Will be automatically normalized
        
        query: Natural language question about the website.
              Examples:
              - "What is their pricing model?"
              - "What are the main features of their product?"
              - "What industries do they serve?"
              - "What is their mission statement?"
              - "What programming languages do they support?"
        
        max_speed: Optimize for speed over accuracy (default: False)
                  - True: Faster response, may be less detailed
                  - False: More thorough analysis, takes longer
        
    Returns:
        JSON string with AI-extracted answer to your query.
        
    Examples:
        # Get pricing information
        ai_query_brand_website(
            domain="stripe.com",
            query="What is their pricing model for payment processing?"
        )
        
        # Extract product features
        ai_query_brand_website(
            domain="unity.com",
            query="What are the main features of Unity game engine?"
        )
        
        # Fast query for quick info
        ai_query_brand_website(
            domain="openai.com",
            query="What AI models do they offer?",
            max_speed=True
        )
        
        # Get target audience info
        ai_query_brand_website(
            domain="roblox.com",
            query="What age group is their platform designed for?"
        )
    
    Use Cases:
        - Competitive research and analysis
        - Gathering specific product information
        - Understanding pricing and business models
        - Extracting technical specifications
        - Finding target demographics
        - Discovering partnerships and integrations
        - Understanding company values and mission
        
    Note:
        - Requires BRAND_DEV_API_KEY in environment variables
        - Results are not cached (dynamic queries)
        - Processing time: 5-30 seconds depending on max_speed
        - Works on any public website, not just known brands
    """
    if not domain or not domain.strip():
        return json.dumps({
            "success": False,
            "error": "Domain cannot be empty"
        })
    
    if not query or not query.strip():
        return json.dumps({
            "success": False,
            "error": "Query cannot be empty"
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
        f"AI querying website via NestJS: domain={domain}, "
        f"query='{query[:50]}...', max_speed={max_speed}"
    )
    
    # Call NestJS POST /brand/ai-query
    # NestJS expects structured data_to_extract, not a simple query string.
    # Transform the free-form query into the structured format.
    timeout_seconds = 15 if max_speed else 60
    
    result = await call_nest_api_async(
        method="POST",
        path="/brand/ai-query",
        json_body={
            "domain": domain.strip(),
            "maxSpeed": max_speed,
            "data_to_extract": [
                {
                    "datapoint_name": "query_result",
                    "datapoint_description": query.strip(),
                    "datapoint_example": "relevant information from the website",
                    "datapoint_type": "text",
                }
            ],
            "specific_pages": {
                "home_page": True,
                "about_us": True,
                "pricing": True,
            },
        },
        user_id=user_id,
        timeout=timeout_seconds,
    )
    
    if not result.get("success"):
        error_msg = result.get("error", "Unknown error")
        logger.error(f"Brand AI query failed: {error_msg}")
        return json.dumps({
            "success": False,
            "error": error_msg,
            "domain": domain,
            "query": query,
        })
    
    # Return the NestJS response data directly
    data = result.get("data", {})
    
    if isinstance(data, dict):
        data["success"] = True
        data["domain"] = domain.strip()
        data["query"] = query
    
    return json.dumps(data, indent=2, default=str)


# Export all tools
BRAND_DATA_TOOLS = [
    get_brand_data,
    ai_query_brand_website,
]
