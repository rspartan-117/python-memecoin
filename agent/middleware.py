import os
import logging
from langchain.chat_models import init_chat_model
from langchain.agents.middleware import (
    AgentMiddleware,
    ContextEditingMiddleware,
    ClearToolUsesEdit,
    SummarizationMiddleware,
)
from langchain_anthropic.middleware.prompt_caching import (
    AnthropicPromptCachingMiddleware,
)

logger = logging.getLogger(__name__)


class MiddlewareConfig:
    # Prompt Caching (CRITICAL for cost reduction)
    CACHE_TTL = "5m"  # 5 minutes cache
    MIN_MESSAGES_TO_CACHE = 3  # Start caching after 3 messages

    # Context Editing (CRITICAL for performance)
    CONTEXT_TRIGGER_TOKENS = 30_000  # Anthropic's limit is 200k
    CLEAR_AT_LEAST_TOKENS = 20_000  # Reclaim at least 20k tokens
    KEEP_RECENT_TOOLS = 3  # Keep last 3 tool results
    EXCLUDED_TOOLS = []  # Never clear these tools

    # Summarization (MEDIUM priority)
    MAX_TOKENS_BEFORE_SUMMARY = 50_000  # Trigger at 150k tokens
    MESSAGES_TO_KEEP = 15  # Keep last 15 messages


def create_middleware_stack() -> list[AgentMiddleware]:
    summary_model = init_chat_model(
        model="gpt-5-mini",
        model_provider="openai",
        streaming=True,
        temperature=0.5,
        timeout=120,  # 2 minutes timeout for summarization
        max_tokens=8000,
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )
    return [
        AnthropicPromptCachingMiddleware(
            type="ephemeral",
            ttl=MiddlewareConfig.CACHE_TTL,
            min_messages_to_cache=MiddlewareConfig.MIN_MESSAGES_TO_CACHE,
            unsupported_model_behavior="ignore",
        ),
        ContextEditingMiddleware(
            edits=[
                ClearToolUsesEdit(
                    trigger=MiddlewareConfig.CONTEXT_TRIGGER_TOKENS,
                    clear_at_least=MiddlewareConfig.CLEAR_AT_LEAST_TOKENS,
                    keep=MiddlewareConfig.KEEP_RECENT_TOOLS,
                    clear_tool_inputs=False,  # Keep tool call parameters
                    exclude_tools=MiddlewareConfig.EXCLUDED_TOOLS,
                    placeholder="[Previous tool output cleared to save context]",
                )
            ],
            token_count_method="approximate",  # Faster than exact counting
        ),
        SummarizationMiddleware(
            model=summary_model,
            max_tokens_before_summary=MiddlewareConfig.MAX_TOKENS_BEFORE_SUMMARY,
            messages_to_keep=MiddlewareConfig.MESSAGES_TO_KEEP,
            # summary_prompt=MiddlewareConfig.PRODUCTION_SUMMARY_PROMPT,
            summary_prefix="## Context Summary:",
        ),
    ]
    