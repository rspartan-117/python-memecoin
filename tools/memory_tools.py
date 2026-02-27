"""Memory Tools for Agent"""

import os
import uuid
import logging
from typing import TypedDict, Any, Literal
from dataclasses import dataclass
from datetime import datetime
from langchain_openai import OpenAIEmbeddings
from langgraph.store.memory import InMemoryStore
from langgraph.store.mongodb import MongoDBStore
from langchain.tools import tool, ToolRuntime
from langchain.agents import AgentState
from dotenv import load_dotenv


load_dotenv()

logger = logging.getLogger(__name__)


# ==================== AGENT STATE SCHEMA ====================
# DEPRECATED: Now using LandingPageAgentState from agent_state/state.py
# class MemoryAgentState(AgentState):
#     """Agent state schema including memory keys for quick retrieval."""
#
#     messages: list
#     memory_keys: list[str]


# ==================== MEMORY STORE SETUP ====================

# NOTE: Store is now provided by CheckpointerService (MongoDBStore)
# The store instance is passed to the agent via test_agent.py
# No need to create a store here - it's managed by the service

# DEPRECATED: InMemoryStore (replaced with MongoDBStore from checkpointer service)
# embeddings = OpenAIEmbeddings(
#     model="text-embedding-3-small", openai_api_key=os.getenv("OPENAI_API_KEY")
# )
#
# store = InMemoryStore(
#     index={
#         "embed": embeddings,
#         "dims": 1536,  # text-embedding-3-small dimensions
#         "fields": [
#             "content"
#         ],  # Fields to index for semantic search -> Content field is automatically embedded for semantic search
#     }
# )
#
# logger.info("✅ Memory store initialized with semantic search")

# logger.info("Memory tools ready (store provided by CheckpointerService)")

# ==================== CONTEXT SCHEMA ====================
# DEPRECATED: Now using RuntimeContext from context/runtime_context.py
# @dataclass
# class MemoryContext:
#     """Runtime context passed to memory tools."""
#
#     user_id: str
#     session_id: str

from context.runtime_context import RuntimeContext
from agent_state import LandingPageAgentState


@tool
def save_to_memory(
    key: str, content: str, runtime: ToolRuntime[RuntimeContext, LandingPageAgentState]
) -> str:
    """
    Save information to long-term memory store for future retrieval.

    Args:
        key: Unique identifier (e.g., "user_preference", "project_name")
        content: The information to remember

    Use when user shares important facts, preferences, or context to remember across sessions.
    """
    # Validate inputs
    if not key or not key.strip():
        return "Error: Memory key cannot be empty"

    if not content or not content.strip():
        return "Error: Memory content cannot be empty"

    try:
        store = runtime.store
        state = runtime.state
        context = runtime.context

        namespace = ("memories", context.session_id)

        # Store in long-term memory
        store.put(
            namespace,
            key.strip(),
            {
                "content": content.strip(),
                "timestamp": datetime.now().isoformat(),
            },
        )

        logger.info(f"[MEMORY] Saved: {key} | {content[:30]}...")

        # Update state
        if "memory_keys" not in state:
            state["memory_keys"] = []

        state["memory_keys"].append(key.strip())

        return f"Saved to memory: {content[:50]}..."

    except Exception as e:
        logger.error(f"[MEMORY] Save error: {e}")
        return f"Failed to save memory: {str(e)}"


@tool
def retrieve_memory(
    query: str = "",
    retrieval_method: Literal["semantic", "direct"] = "semantic",
    limit: int = 5,
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState] = None,
) -> str:
    """
    Retrieve information from long-term memory store.

    Args:
        query: Memory key (for direct) or search phrase (for semantic). Empty for listing all.
        retrieval_method: "direct" for exact key lookup, "semantic" for meaning-based search
        limit: Max results for semantic search (1-10). Use 0 with direct method to list all memories.

    Use to recall previously saved information from memory store.
    """
    if not runtime:
        return "Error: Runtime not available"

    try:
        store = runtime.store
        context = runtime.context
        namespace = ("memories", context.session_id)

        # List all memories when limit=0 and method=direct
        if retrieval_method == "direct" and limit == 0:
            logger.info("[MEMORY] Listing all memories")

            # Use search with no query and high limit to get all items
            all_items = store.search(namespace, limit=100)

            if not all_items:
                return "No memories stored yet"

            formatted = []
            for i, item in enumerate(all_items, 1):
                key = item.key if hasattr(item, "key") else "unknown"
                content = item.value.get("content", "")
                if content:
                    formatted.append(f"{i}. [{key}] {content}")

            return "\n".join(formatted) if formatted else "No valid memories found"

        # Validate query for other operations
        if not query or not query.strip():
            return "Error: Query cannot be empty (use limit=0 with direct method to list all)"

        if limit < 1 or limit > 10:
            limit = 5

        # Direct key lookup
        if retrieval_method == "direct":
            item = store.get(namespace, query.strip())

            if item:
                content = item.value.get("content", "")
                logger.info(f"[MEMORY] Retrieved: {query}")
                return content if content else "Memory found but empty"
            else:
                logger.warning(f"[MEMORY] Not found: {query}")
                return f"No memory found for key: {query}"

        # Semantic search
        elif retrieval_method == "semantic":
            results = store.search(namespace, query=query.strip(), limit=limit)

            if not results:
                logger.info(f"[MEMORY] No matches: {query}")
                return f"No memories found for: {query}"

            logger.info(f"[MEMORY] Found {len(results)} results")

            # Format as numbered list
            formatted = []
            for i, item in enumerate(results, 1):
                content = item.value.get("content", "")
                if content:
                    formatted.append(f"{i}. {content}")

            return "\n".join(formatted) if formatted else "No valid results found"

    except Exception as e:
        logger.error(f"[MEMORY] Retrieval error: {e}")
        return f"Failed to retrieve memory: {str(e)}"


MEMORY_TOOLS = [
    save_to_memory,
    retrieve_memory,
]

# logger.info(f"✅ Exported {len(MEMORY_TOOLS)} memory tools")


