"""
Production Singleton Agent
===========================

Creates agent ONCE on startup, reuses for all requests.
This is the PRODUCTION approach for FastAPI/web servers.
"""

import os
import asyncio
import logging
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from checkpoint import get_checkpointer_service
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    SummarizationMiddleware,
)
from context.runtime_context import RuntimeContext
from agent_state import LandingPageAgentState
from tools.tool_loader import load_all_tools
from agent.prompts.landing_page_system_prompt import LANDING_PAGE_SYSTEM_PROMPT

load_dotenv()


class MiddlewareConfig:
    """Production middleware configuration"""

    CACHE_TTL = "5m"  # 5 minutes cache
    MIN_MESSAGES_TO_CACHE = 3  # Start caching after 3 messages

    # Context Editing (CRITICAL for performance)
    CONTEXT_TRIGGER_TOKENS = 50000  # Anthropic's limit is 200k
    CLEAR_AT_LEAST_TOKENS = 20000  # Reclaim at least 20k tokens
    KEEP_RECENT_TOOLS = 3  # Keep last 3 tool results
    EXCLUDED_TOOLS = []  # Tools to exclude from context clearing

    # Summarization (MEDIUM priority)
    MAX_TOKENS_BEFORE_SUMMARY = 40000  # Trigger at 150k tokens
    MESSAGES_TO_KEEP = 7  # Keep last 3 messages

    # Metadata Extraction (Always enabled)
    REQUIRED_FIELDS = ["phase", "thinking", "next_steps"]

    # Dynamic Prompts (State-aware)
    ENABLE_PHASE_PROMPTS = True


logger = logging.getLogger(__name__)

# Global agent (singleton)
_agent = None
_agent_lock = asyncio.Lock()


async def get_agent():
    """
    Get singleton agent instance.

    Creates agent ONCE on first call, reuses for all subsequent requests.
    This is the PRODUCTION approach for FastAPI/web servers.
    """
    global _agent

    if _agent is not None:
        return _agent

    async with _agent_lock:
        # Double-check after acquiring lock
        if _agent is not None:
            return _agent

        logger.info("[AGENT] Initializing singleton agent...")

        # Load all tools
        all_tools = load_all_tools()
        logger.info(f"Loaded {len(all_tools)} tools for agent")

        # Get checkpointer service (singleton pattern)
        checkpointer_service = await get_checkpointer_service()

        # Ensure checkpointer initialized
        if not checkpointer_service._initialized:
            await checkpointer_service.initialize()

        # Get checkpointer instance (shared across all requests)
        checkpointer = checkpointer_service.get_checkpointer()

        # Get store instance (shares same MongoDB client)
        store = checkpointer_service.get_store()
        logger.info("Retrieved checkpointer + store from service")

        # Create model
        chat_model = init_chat_model(
            model="claude-sonnet-4-5-20250929",
            model_provider="anthropic",
            streaming=True,
            temperature=0.5,
            timeout=300,  # 5 minutes timeout for long-running operations
            max_tokens=1000,
            configurable_fields=(
                "model",
                "model_provider",
                "streaming",
                "temperature",
                "timeout",
                "max_tokens",
                "base_url",
                "api_key",
            ),
        )

        # Create summary model for middleware (initialized here to avoid module-level blocking)
        summary_model = init_chat_model(
            model="x-ai/grok-4.1-fast",
            model_provider="openai",
            streaming=True,
            temperature=0.5,
            timeout=120,  # 2 minutes timeout for summarization
            max_tokens=2000,
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )

        # Create agent ONCE
        _agent = create_agent(
            model=chat_model,
            debug=True,
            system_prompt=LANDING_PAGE_SYSTEM_PROMPT,
            checkpointer=checkpointer,
            name="LANDING_PAGE_AGENT",
            tools=all_tools,
            state_schema=LandingPageAgentState,
            store=store,
            context_schema=RuntimeContext,
            middleware=[
                ContextEditingMiddleware(
                    edits=[
                        ClearToolUsesEdit(
                            trigger=MiddlewareConfig.CONTEXT_TRIGGER_TOKENS,
                            clear_at_least=MiddlewareConfig.CLEAR_AT_LEAST_TOKENS,
                            keep=MiddlewareConfig.KEEP_RECENT_TOOLS,
                            clear_tool_inputs=False,
                            exclude_tools=MiddlewareConfig.EXCLUDED_TOOLS,
                            placeholder="[Previous tool output cleared to save context]",
                        )
                    ],
                    token_count_method="approximate",
                ),
                SummarizationMiddleware(
                    model=summary_model,  # Use locally initialized model
                    max_tokens_before_summary=MiddlewareConfig.MAX_TOKENS_BEFORE_SUMMARY,
                    messages_to_keep=MiddlewareConfig.MESSAGES_TO_KEEP,
                    summary_prefix="## Context Summary:",
                ),
            ],
        )

        logger.info("Agent initialized (singleton)")

        return _agent
