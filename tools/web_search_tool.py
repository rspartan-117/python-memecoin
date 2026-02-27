"""
Web Search Tool for LangGraph
"""

import os
import json
import dotenv
from langchain.tools import tool
from parallel import Parallel

dotenv.load_dotenv()


@tool
def search_web(query: str) -> str:
    """
    Search the web using Parallel AI Search API and return results.

    Args:
        query: Search query string (used as objective)

    Returns:
        JSON string with search results or error message
    """
    api_key = os.getenv("PARALLEL_API_KEY")
    if not api_key:
        return json.dumps(
            {
                "success": False,
                "error": "PARALLEL_API_KEY not found in environment variables",
            }
        )

    # Get configuration from environment variables with defaults
    # max_results = int(os.getenv("PARALLEL_MAX_RESULTS", "10"))
    processor = os.getenv("PARALLEL_PROCESSOR", "lite")

    try:
        client = Parallel(api_key=api_key)
        # Create task run instead of beta.search
        run = client.task_run.create(input=query, processor=processor)

        # Poll until complete (simple sync approach)
        while run.status != "completed":
            run = client.task_run.retrieve(run.run_id)
            if run.status == "failed":
                return json.dumps(
                    {
                        "success": False,
                        "error": "Task run failed",
                    }
                )

        # Get the final results using the result() method
        run_result = client.task_run.result(run.run_id)

        # Extract only the content for token efficiency
        # For debugging/error-solving, we don't need citations and reasoning
        content_text = ""
        source_urls = []

        if hasattr(run_result, "output"):
            # Extract the main content
            if hasattr(run_result.output, "content"):
                if hasattr(run_result.output.content, "output"):
                    content_text = str(run_result.output.content.output)
                elif hasattr(run_result.output.content, "__dict__"):
                    content_dict = run_result.output.content.__dict__
                    content_text = content_dict.get(
                        "output", str(run_result.output.content)
                    )
                else:
                    content_text = str(run_result.output.content)

            # Collect unique source URLs for reference (lightweight)
            if hasattr(run_result.output, "basis"):
                for basis_item in run_result.output.basis:
                    if hasattr(basis_item, "citations"):
                        for citation in basis_item.citations:
                            url = getattr(citation, "url", "")
                            if url and url not in source_urls:
                                source_urls.append(url)

        # Return lightweight response optimized for LLM consumption
        response = {
            "success": True,
            "query": query,
            "content": content_text,
            "sources": source_urls[:5],  # Limit to top 5 sources
            "processor": processor,
        }

        return json.dumps(response, indent=2)

    except ImportError:
        return json.dumps(
            {
                "success": False,
                "error": "parallel library not available. Install with: pip install parallel",
            }
        )
    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "error": f"Search request failed: {str(e)}. Check PARALLEL_API_KEY, PARALLEL_MAX_RESULTS (default: 10), PARALLEL_PROCESSOR (default: base) env vars.",
            }
        )


# Export for agent
SEARCH_TOOL = search_web
