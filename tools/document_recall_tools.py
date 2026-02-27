"""
Document Recall Tools for Agent

RAG (Retrieval-Augmented Generation) tools that enable the agent to search
and retrieve relevant information from uploaded documents using semantic search.

These tools integrate with the DocumentProcessor's vector store to provide
context-aware information retrieval for landing page generation tasks.
"""

import logging
from typing import List, Dict, Any, Optional
from langchain.tools import tool, ToolRuntime
from context.runtime_context import RuntimeContext
from agent_state import LandingPageAgentState

logger = logging.getLogger(__name__)


# Global document processor (singleton pattern)
_document_processor = None


def get_document_processor():
    """
    Get or create document processor singleton.
    
    Returns:
        DocumentProcessor instance for searching documents
    """
    global _document_processor
    if _document_processor is None:
        from processors.document_processor import DocumentProcessor
        _document_processor = DocumentProcessor()
        logger.info("DocumentProcessor initialized for recall tools")
    return _document_processor


@tool
async def search_documents(
    query: str,
    max_results: int = 5,
    file_type: Optional[str] = None,
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState] = None,
) -> str:
    """
    Search uploaded documents using semantic similarity search.

    Use this tool to find relevant information from documents that have been
    uploaded to the current session. Perfect for recalling game requirements,
    design specs, code examples, or any other documentation.

    Args:
        query: What you're looking for (e.g., "authentication implementation", 
               "game mechanics", "player movement code")
        max_results: Number of relevant chunks to return (default: 5, max: 20)
        file_type: Optional filter by file extension (e.g., "py", "pdf", "md")
                  Useful when you only want to search specific file types

    Returns:
        Formatted string with relevant document chunks, including:
        - Chunk content (the actual text/code)
        - Filename and file type
        - Whether it's a code file and the programming language
        
    Examples:
        # Search all documents
        search_documents("How should the player movement work?")
        
        # Search only Python files
        search_documents("authentication implementation", file_type="py")
        
        # Get more results for broader context
        search_documents("game design requirements", max_results=10)
        
    Use Cases:
        - Finding implementation details from code examples
        - Recalling game requirements or design decisions
        - Looking up API documentation or libraries mentioned in docs
        - Finding specific algorithms or logic from uploaded files
        - Retrieving context about the game genre, mechanics, or story
    """
    # Validate inputs
    if not query or not query.strip():
        return "Error: Search query cannot be empty."
    
    # Cap max_results at 20 for performance
    if max_results > 20:
        logger.warning(f"max_results capped at 20 (requested: {max_results})")
        max_results = 20
    elif max_results < 1:
        return "Error: max_results must be at least 1."
    
    try:
        # Get session_id from runtime context
        if not runtime or not runtime.context:
            return "Error: Cannot access session context."
        
        session_id = runtime.context.session_id
        
        if not session_id:
            return "Error: No session_id found in context."
        
        # Get document processor
        processor = get_document_processor()
        
        # Perform semantic search
        logger.info(
            f"Searching documents: query='{query[:50]}...', "
            f"session_id={session_id}, max_results={max_results}, "
            f"file_type={file_type or 'all'}"
        )
        
        results = await processor.search_documents(
            query=query.strip(),
            session_id=session_id,
            max_results=max_results,
            file_type=file_type,
        )
        
        # Handle no results
        if not results:
            file_filter_msg = f" (file_type={file_type})" if file_type else ""
            return f"No documents found for query: '{query}'{file_filter_msg}"
        
        # Format results for agent consumption
        formatted_output = []
        formatted_output.append(f"Found {len(results)} relevant chunks for: '{query}'\n")
        
        if file_type:
            formatted_output.append(f"Filtered by: {file_type}\n")
        
        formatted_output.append("\n")
        
        for idx, result in enumerate(results, 1):
            filename = result.get("filename", "unknown")
            content = result.get("content", "")
            file_type_ext = result.get("file_type", "")
            language = result.get("language")
            is_code = result.get("is_code_file", False)
            chunk_index = result.get("chunk_index")
            total_chunks = result.get("total_chunks")
            
            # Header for each result
            formatted_output.append(f"\n[{idx}] {filename}")
            
            if file_type_ext:
                formatted_output.append(f" (.{file_type_ext})")
            
            if is_code and language:
                formatted_output.append(f" [{language}]")
            
            # Chunk info
            if chunk_index is not None and total_chunks:
                formatted_output.append(f" (chunk {chunk_index + 1}/{total_chunks})")
            
            formatted_output.append("\n")
            
            # Content
            formatted_output.append(f"{content}\n")
        
        return "".join(formatted_output)
        
    except ValueError as ve:
        # Validation errors from search_documents
        logger.error(f"Validation error in document search: {ve}")
        return f"Validation Error: {str(ve)}"
    
    except Exception as e:
        # Unexpected errors
        logger.error(f"Error searching documents: {e}", exc_info=True)
        return f"Error searching documents: {str(e)}"


@tool
async def list_session_documents(
    runtime: ToolRuntime[RuntimeContext, LandingPageAgentState] = None,
) -> str:
    """
    List all documents uploaded to the current session.

    Use this tool to see what documents are available for search and retrieval.
    Helpful for understanding what information sources you have access to.

    Returns:
        Formatted list of all documents in the session with metadata:
        - Filename and file type
        - Document summary
        - Number of chunks and tokens
        - Whether it's a code file and the language
        
    Examples:
        # See what's available
        list_session_documents()
        
    Use Cases:
        - Checking what documents have been uploaded before searching
        - Understanding the scope of available information
        - Verifying a specific document was processed successfully
        - Getting an overview of code files vs documentation
    """
    try:
        # Get session_id from runtime context
        if not runtime or not runtime.context:
            return "Error: Cannot access session context."
        
        session_id = runtime.context.session_id
        
        if not session_id:
            return "Error: No session_id found in context."
        
        # Get document processor
        processor = get_document_processor()
        
        # Get list of session documents
        logger.info(f"Listing documents for session: {session_id}")
        
        documents = await processor.list_session_documents(session_id=session_id)
        
        # Handle no documents
        if not documents:
            return "No documents found in this session."
        
        # Format output
        formatted_output = []
        formatted_output.append(f"Documents in session: {len(documents)}\n")
        
        for idx, doc in enumerate(documents, 1):
            filename = doc.get("filename", "unknown")
            file_type = doc.get("file_type", "")
            language = doc.get("language")
            is_code = doc.get("is_code_file", False)
            summary = doc.get("summary", "No summary available")
            total_chunks = doc.get("total_chunks", 0)
            token_count = doc.get("token_count", 0)
            
            formatted_output.append(f"\n{idx}. {filename}")
            
            if file_type:
                formatted_output.append(f" (.{file_type})")
            
            if is_code and language:
                formatted_output.append(f" [{language}]")
            
            formatted_output.append("\n")
            formatted_output.append(f"   Summary: {summary}\n")
            formatted_output.append(f"   Chunks: {total_chunks} | Tokens: {token_count:,}\n")
        
        formatted_output.append("\nUse search_documents() to find specific information.")
        
        return "".join(formatted_output)
        
    except Exception as e:
        logger.error(f"Error listing session documents: {e}", exc_info=True)
        return f"Error listing documents: {str(e)}"

