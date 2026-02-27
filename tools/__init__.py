"""
Tools Package for LangGraph Agent
==================================

This package provides all tools for the landing page generation agent, organized by category:

- Command Tools: E2B sandbox command execution (run_command, list_processes, etc.)
- File Tools: File operations (read, write, list, create, delete)
- Edit Tools: Code editing with intelligent matching strategies
- Memory Tools: Persistent memory storage and retrieval
- Web Search Tool: Web search via Parallel AI
- Fal Generation Tools: Image generation and transformation via Fal.ai
- Brand Data Tools: Brand assets and website data via Brand.dev

All tools require RuntimeContext with user_id and project_id.
"""

# =============================================================================
# COMMAND TOOLS
# =============================================================================

from .command_tools_e2b import (
    COMMAND_TOOLS,
    CORE_COMMAND_TOOLS,
)

# =============================================================================
# FILE TOOLS
# =============================================================================

from .file_tools_e2b import (
    FILE_TOOLS,
    create_file_tools,
)

# =============================================================================
# EDIT TOOLS
# =============================================================================

from .edit_tools_e2b import (
    EDIT_TOOLS,
)

# =============================================================================
# MEMORY TOOLS
# =============================================================================

from .memory_tools import (
    MEMORY_TOOLS,
    save_to_memory,
    retrieve_memory,
)
# DEPRECATED: MemoryAgentState and MemoryContext are now integrated into:
# - RuntimeContext (from context/runtime_context.py) - includes session_id property
# - LandingPageAgentState (from agent_state/state.py) - includes messages and memory_keys fields

# =============================================================================
# WEB SEARCH TOOL
# =============================================================================

from .web_search_tool import (
    SEARCH_TOOL,
    search_web,
)

# =============================================================================
# DOCUMENT RECALL TOOLS (RAG)
# =============================================================================

from .document_recall_tools import (
    search_documents,
    list_session_documents,
)

# =============================================================================
# FAL GENERATION TOOLS
# =============================================================================

from .fal_text_to_image_tool import generate_image_text_to_image
from .fal_img_to_img_tool import generate_image_img_to_img
from .fal_remove_bg_tool import remove_background_from_image

# Aggregate Fal tools
FAL_GENERATION_TOOLS = [
    generate_image_text_to_image,
    generate_image_img_to_img,
    remove_background_from_image,
]

# =============================================================================
# BRAND DATA TOOLS
# =============================================================================

from .brand_data_tools import (
    BRAND_DATA_TOOLS,
    get_brand_data,
    ai_query_brand_website,
)

# =============================================================================
# AGGREGATED TOOL COLLECTIONS
# =============================================================================

# Document recall tools
DOCUMENT_RECALL_TOOLS = [
    search_documents,
    list_session_documents,
]

# All tools combined
ALL_TOOLS = [
    *COMMAND_TOOLS,
    *FILE_TOOLS,
    *EDIT_TOOLS,
    *MEMORY_TOOLS,
    SEARCH_TOOL,
    *DOCUMENT_RECALL_TOOLS,
    *FAL_GENERATION_TOOLS,
    *BRAND_DATA_TOOLS,
]

# Sandbox-specific tools (E2B operations)
SANDBOX_TOOLS = [
    *COMMAND_TOOLS,
    *FILE_TOOLS,
    *EDIT_TOOLS,
]

# Agent enhancement tools (memory, search, document recall)
AGENT_TOOLS = [
    *MEMORY_TOOLS,
    SEARCH_TOOL,
    *DOCUMENT_RECALL_TOOLS,
]

# Generation and branding tools
GENERATION_TOOLS = [
    *FAL_GENERATION_TOOLS,
    *BRAND_DATA_TOOLS,
]

# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Command tools
    "COMMAND_TOOLS",
    "CORE_COMMAND_TOOLS",
    # File tools
    "FILE_TOOLS",
    "create_file_tools",
    # Edit tools
    "EDIT_TOOLS",
    # Memory tools
    "MEMORY_TOOLS",
    "save_to_memory",
    "retrieve_memory",
    # Web search
    "SEARCH_TOOL",
    "search_web",
    # Document recall
    "DOCUMENT_RECALL_TOOLS",
    "search_documents",
    "list_session_documents",
    # Fal generation tools
    "FAL_GENERATION_TOOLS",
    "generate_image_text_to_image",
    "generate_image_img_to_img",
    "remove_background_from_image",
    # Brand data tools
    "BRAND_DATA_TOOLS",
    "get_brand_data",
    "ai_query_brand_website",
    # Aggregated collections
    "ALL_TOOLS",
    "SANDBOX_TOOLS",
    "AGENT_TOOLS",
    "GENERATION_TOOLS",
]

# =============================================================================
# METADATA
# =============================================================================

__version__ = "1.0.0"

# Tool counts for reference
TOOL_COUNTS = {
    "command": len(COMMAND_TOOLS),
    "document_recall": len(DOCUMENT_RECALL_TOOLS),
    "file": len(FILE_TOOLS),
    "edit": len(EDIT_TOOLS),
    "memory": len(MEMORY_TOOLS),
    "search": 1,
    "fal_generation": len(FAL_GENERATION_TOOLS),
    "brand_data": len(BRAND_DATA_TOOLS),
    "total": len(ALL_TOOLS),
}
