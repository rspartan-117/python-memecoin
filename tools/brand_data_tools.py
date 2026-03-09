"""
Brand.dev Data Tools for Meme Coin Landing Page Generation
===========================================================

Tools for retrieving brand assets (logos, colors, fonts) and AI-powered
data extraction from company/crypto project websites.

Use these tools to:
- Extract brand colors, fonts, and logos from existing crypto projects
- Research competitor meme coin websites for styling inspiration
- Query specific information from crypto project pages

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
    Retrieve comprehensive brand data for a crypto project or company using Brand.dev API.
    
    Fetches brand assets including logos, colors, fonts, descriptions, and social links.
    Perfect for extracting the visual identity of existing meme coins or crypto projects
    to inspire or theme your landing page design.
    
    Results are cached for 1 hour to improve performance and reduce API calls.
    
    Args:
        domain: Company domain or website URL.
               Examples: "uniswap.org", "https://nike.com", "www.apple.com"
               Will be automatically normalized (protocol and www removed)
        
        force_refresh: Bypass cache and fetch fresh data from API (default: False)
                      Use when you need the most up-to-date brand information
        
    Returns:
        JSON string with brand data including:
        - title: Project/company name
        - description: Project description
        - logos: Array of logo URLs in various sizes and formats
        - colors: Array of brand colors with hex codes and names (use for landing page palette)
        - fonts: Array of brand fonts with names and weights (use for landing page typography)
        - links: Social media and other important links (use for community section)
        - cached: Whether this data came from cache
        
    Examples:
        # Get brand colors from an existing meme coin for styling inspiration
        get_brand_data(domain="dogecoin.com")
        
        # Extract visual identity from a DeFi project
        get_brand_data(domain="uniswap.org")
        
        # Force fresh data from a recently updated crypto project
        get_brand_data(domain="https://shib.io", force_refresh=True)
    
    Use Cases for Meme Coin Landing Pages:
        - Extract color palettes from successful meme coins (Dogecoin yellow, Shiba orange)
        - Get official fonts to match existing crypto project aesthetics
        - Find social media links to reference in community sections
        - Gather logos for creating similar-styled mascots
        - Research competitor brand guidelines for design inspiration
        - Build themed landing pages matching established crypto brands
    """
    try:
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
        
    except Exception as e:
        # Catch-all error handler - ensures tool never raises exceptions
        logger.error(f"Unexpected error in get_brand_data: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"Unexpected error occurred: {str(e)}",
            "domain": domain if domain else "unknown",
        })


@tool
async def ai_query_brand_website(
    domain: str,
    query: str,
    max_speed: bool = False,
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState] = None,
) -> str:
    """
    Extract custom data from any website using AI-powered natural language queries.
    
    Ask natural language questions about a meme coin or crypto project's website 
    and get AI-extracted answers. Perfect for competitive research and gathering 
    specific information not available in standard brand data.
    
    Args:
        domain: Company domain or website URL to query.
               Examples: "stripe.com", "https://openai.com"
               Will be automatically normalized
        
        query: Natural language question about the website.
              Examples for crypto/meme coin research:
              - "What is their tokenomics structure?"
              - "What blockchain does this project use?"
              - "What is their total supply and distribution?"
              - "What are the main features of their project?"
              - "What exchanges is the token listed on?"
        
        max_speed: Optimize for speed over accuracy (default: False)
                  - True: Faster response, may be less detailed
                  - False: More thorough analysis, takes longer
        
    Returns:
        JSON string with AI-extracted answer to your query.
        
    Examples:
        # Research tokenomics from a competitor meme coin
        ai_query_brand_website(
            domain="dogecoin.com",
            query="What is their tokenomics and supply structure?"
        )
        
        # Extract roadmap information
        ai_query_brand_website(
            domain="shib.io",
            query="What are the main phases in their project roadmap?"
        )
        
        # Fast query for blockchain info
        ai_query_brand_website(
            domain="uniswap.org",
            query="What blockchain networks do they support?",
            max_speed=True
        )
        
        # Get community information
        ai_query_brand_website(
            domain="safemoon.com",
            query="What community initiatives and rewards do they offer?"
        )
    
    Use Cases for Meme Coin Landing Pages:
        - Research competitor tokenomics for your landing page content
        - Extract roadmap structures to inspire your own timeline
        - Discover team presentation styles from successful projects
        - Find popular features to highlight in your landing page
        - Gather exchange listings and partnerships for credibility
        - Understand community engagement strategies
        - Learn how successful projects communicate their value proposition
        - Extract technical details to include in your "About" section
        
    Note:
        - Results are not cached (dynamic queries)
        - Processing time: 5-30 seconds depending on max_speed
        - Works on any public website, including crypto projects and DeFi platforms
        - Use this for content research when building landing page sections
    """
    try:
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
        
    except Exception as e:
        # Catch-all error handler - ensures tool never raises exceptions
        logger.error(f"Unexpected error in ai_query_brand_website: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"Unexpected error occurred: {str(e)}",
            "domain": domain if domain else "unknown",
            "query": query if query else "unknown",
        })


# Export all tools
BRAND_DATA_TOOLS = [
    get_brand_data,
    ai_query_brand_website,
]
