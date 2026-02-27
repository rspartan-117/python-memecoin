"""
Tool loading for the landing page generation agent.

Loads all available tools from different modules.
"""

import logging
from typing import List
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


def load_all_tools() -> List[BaseTool]:
    """
    Load all available tools for the agent.

    Returns:
        List of LangChain tools ready for agent use
    """
    tools = []

    # File Tools (E2B Sandbox)
    try:
        from tools.file_tools_e2b import (
            read_file,
            write_file,
            file_exists,
            list_directory,
            create_directory,
            delete_file,
            batch_read_files,
            batch_write_files,
        )

        file_tools = [
            read_file,
            write_file,
            file_exists,
            list_directory,
            create_directory,
            delete_file,
            batch_read_files,
            batch_write_files,
        ]

        tools.extend(file_tools)
        logger.info(f"Loaded {len(file_tools)} file tools")
    except Exception as e:
        logger.error(f"Failed to load file tools: {e}", exc_info=True)

    # Edit Tools (E2B Sandbox)
    try:
        from tools.edit_tools_e2b import (
            edit_file,
            smart_edit_file,
        )

        edit_tools = [
            edit_file,
            smart_edit_file,
        ]

        tools.extend(edit_tools)
        logger.info(f"Loaded {len(edit_tools)} edit tools")
    except Exception as e:
        logger.error(f"Failed to load edit tools: {e}", exc_info=True)

    # Command Tools (E2B Sandbox)
    try:
        from tools.command_tools_e2b import (
            run_command,
            list_processes,
            kill_process,
        )
        # get_service_url removed - explicit API route available for getting public URL

        command_tools = [
            run_command,
            list_processes,
            kill_process,
            # get_service_url removed - explicit API route available for getting public URL
        ]

        tools.extend(command_tools)
        logger.info(f"Loaded {len(command_tools)} command tools")
    except Exception as e:
        logger.error(f"Failed to load command tools: {e}", exc_info=True)

    # Memory Tools
    try:
        from tools.memory_tools import (
            save_to_memory,
            retrieve_memory,
        )

        memory_tools = [
            save_to_memory,
            retrieve_memory,
        ]

        tools.extend(memory_tools)
        logger.info(f"Loaded {len(memory_tools)} memory tools")
    except Exception as e:
        logger.error(f"Failed to load memory tools: {e}", exc_info=True)

    # Web Search Tool
    try:
        from tools.web_search_tool import search_web

        tools.append(search_web)
        logger.info("Loaded search_web tool")
    except Exception as e:
        logger.error(f"Failed to load web search tool: {e}", exc_info=True)

    # Document Recall Tools (RAG)
    try:
        from tools.document_recall_tools import (
            search_documents,
            list_session_documents,
        )

        document_recall_tools = [
            search_documents,
            list_session_documents,
        ]

        tools.extend(document_recall_tools)
        logger.info(f"Loaded {len(document_recall_tools)} document recall tools")
    except Exception as e:
        logger.error(f"Failed to load document recall tools: {e}", exc_info=True)

    # Fal Generation Tools
    try:
        from tools.fal_text_to_image_tool import generate_image_text_to_image
        from tools.fal_img_to_img_tool import generate_image_img_to_img
        from tools.fal_remove_bg_tool import remove_background_from_image

        fal_generation_tools = [
            generate_image_text_to_image,
            generate_image_img_to_img,
            remove_background_from_image,
        ]

        tools.extend(fal_generation_tools)
        logger.info(f"Loaded {len(fal_generation_tools)} Fal.ai generation tools")
    except Exception as e:
        logger.error(f"Failed to load Fal generation tools: {e}", exc_info=True)

    # Brand Data Tools
    try:
        from tools.brand_data_tools import (
            get_brand_data,
            ai_query_brand_website,
        )

        brand_data_tools = [
            get_brand_data,
            ai_query_brand_website,
        ]

        tools.extend(brand_data_tools)
        logger.info(f"Loaded {len(brand_data_tools)} Brand.dev data tools")
    except Exception as e:
        logger.error(f"Failed to load brand data tools: {e}", exc_info=True)

    return tools