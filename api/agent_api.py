from fastapi import FastAPI, HTTPException
import json
import os
import time
import logging
from datetime import datetime
from enum import Enum
from typing import AsyncGenerator, Optional, List
from pydantic import BaseModel
from contextlib import asynccontextmanager
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from agent.singleton_agent import get_agent
from checkpoint import get_checkpointer_service
from context.runtime_context import RuntimeContext
from .asset_upload_routes import router as asset_router
from .sandbox_routes import router as sandbox_router
from .zip_download_api import router as zip_download_router

logger = logging.getLogger("api")

# Global agent reference
_agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan handler for application lifecycle management.
    Initializes checkpointer on startup and closes on shutdown.
    """
    global _agent

    # ==================== STARTUP ====================
    logger.info("[APP] Starting application...")

    try:
        # Initialize checkpointer service (creates MongoDB connection)
        checkpointer_service = await get_checkpointer_service()
        await checkpointer_service.initialize()
        logger.info("Checkpointer initialized")

        # Create singleton agent (lazy initialization on first call is also fine)
        _agent = await get_agent()
        logger.info("Agent created with checkpointer")

        logger.info("[APP] All services ready!")

    except Exception as e:
        logger.error(f"[APP] Startup failed: {e}", exc_info=True)
        raise

    yield

    # ==================== SHUTDOWN ====================
    logger.info("[APP] Shutting down...")

    # Close checkpointer service
    checkpointer_service = await get_checkpointer_service()
    await checkpointer_service.close()
    logger.info("Checkpointer connections closed")


app = FastAPI(
    title="Landing Page Generation Agent Streaming API",
    description="Real-time streaming API for AI agent with memory and conversation persistence",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for frontend
# TODO: Configure specific origins for production deployment
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # PRODUCTION: Replace with specific frontend URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include asset upload routes
app.include_router(asset_router)

# Include sandbox session management routes
app.include_router(sandbox_router)

# Include ZIP download routes
app.include_router(zip_download_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Landing Page Generation API is running"}


def format_sse_event(event_type: str, data: dict) -> str:
    """Format Server-Sent Event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# ========== REQUEST MODELS ==========


class ModelProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE_GENAI = "google_genai"
    OPENROUTER = "openrouter"


class DocumentContext(BaseModel):
    """Document context for chat requests"""

    filename: str
    type: str  # File type/extension
    summary: str  # Document summary


class ProjectHistoryRequest(BaseModel):
    """Request model for getting project history"""

    project_id: str
    limit: int = 50


class ProjectStateRequest(BaseModel):
    """Request model for getting project state"""

    project_id: str


class DeleteProjectRequest(BaseModel):
    """Request model for deleting project"""

    project_id: str


class MessageRequest(BaseModel):
    message: str
    project_id: (
        str  # Required for conversation memory and context (project_id = session_id)
    )
    user_id: str = "default-user"  # User ID for memory namespace
    model: str = "x-ai/grok-4-fast"
    model_provider: ModelProvider = ModelProvider.OPENROUTER
    streaming: bool = True
    temperature: float = 0.5
    timeout: int = 300  # 5 minutes timeout for long-running agent operations
    max_tokens: int = 1000
    # Asset context (provided by NestJS from Project.metadata)
    image_urls: Optional[List[str]] = None  # Image URLs for vision model input
    document_context: Optional[List[DocumentContext]] = (
        None  # Document summaries for context
    )


# ========== AGENT ENDPOINT ==========


@app.post("/chat")
async def chat(request: MessageRequest):
    """
    Chat with agent using streaming response.
    Supports multiple model providers (OpenAI, Anthropic, Google, OpenRouter).
    """
    start = time.monotonic()

    try:
        start_time = datetime.now()
        first_response_time = None

        config = {
            "configurable": {
                "thread_id": request.project_id,  # For conversation persistence (checkpointer) - project_id is used as thread_id
                "user_id": request.user_id,  # For memory namespace
                "session_id": request.project_id,  # For memory context - project_id is used as session_id
                "model": request.model,
                "model_provider": request.model_provider.value,
                "streaming": request.streaming,
                "temperature": request.temperature,
                "timeout": request.timeout,
                "max_tokens": request.max_tokens,
            }
        }

        # Handle OpenRouter specially
        if request.model_provider.value == "openrouter":
            config["configurable"]["model_provider"] = "openai"
            config["configurable"]["base_url"] = "https://openrouter.ai/api/v1"
            config["configurable"]["api_key"] = os.getenv("OPENROUTER_API_KEY")

        async def generate():
            nonlocal first_response_time
            completed_successfully = False
            had_error = False

            try:
                # Accumulate token usage across ALL AI calls in this turn.
                # A single agent turn involves multiple LLM calls (tool-calling loop).
                # Previously only the LAST call's usage_metadata was captured,
                # causing all intermediate calls to go uncharged.
                cumulative_input_tokens = 0
                cumulative_output_tokens = 0
                cumulative_total_tokens = 0
                model_provider = None
                model_name = None

                # Send start event
                yield format_sse_event(
                    "agent_start",
                    {
                        "timestamp": datetime.now().isoformat(),
                        "project_id": request.project_id,
                        "user_id": request.user_id,
                    },
                )

                # Get singleton agent
                agent = await get_agent()

                # Create runtime context (includes memory session_id)
                runtime_context = RuntimeContext(
                    user_id=request.user_id,
                    project_id=request.project_id,  # project_id is used as session_id for memory
                )

                # Build message content with asset context
                message_content = request.message

                # Add document context if available
                if request.document_context:
                    doc_context_lines = ["\n[Uploaded Documents Context]"]
                    for doc in request.document_context:
                        doc_context_lines.append(
                            f"- {doc.filename} ({doc.type}): {doc.summary[:200]}..."
                        )
                    message_content = (
                        "\n".join(doc_context_lines) + "\n\n" + message_content
                    )

                # Build message content (supporting images if present)
                if request.image_urls:
                    # Create message with images for vision models
                    message_parts = [{"type": "text", "text": message_content}]
                    for image_url in request.image_urls:
                        message_parts.append(
                            {"type": "image_url", "image_url": {"url": image_url}}
                        )
                    human_message = HumanMessage(content=message_parts)
                else:
                    human_message = HumanMessage(content=message_content)

                async for stream_mode, chunk in agent.astream(
                    {
                        "messages": [human_message],
                        "memory_keys": [],  # Initialize memory_keys in state
                        "user_id": request.user_id,  # Pass user_id to state
                        "project_id": request.project_id,  # Pass project_id to state
                    },
                    config=config,
                    stream_mode=["updates", "messages"],
                    context=runtime_context,  # Pass runtime context to tools
                    durability="async",
                ):
                    # Track first response time
                    if first_response_time is None:
                        first_response_time = datetime.now()

                    # Handle state updates (node transitions)
                    if stream_mode == "updates":
                        for node_name, node_data in chunk.items():
                            if node_data is None:
                                continue

                            messages = node_data.get("messages", [])
                            if messages:
                                last_message = messages[-1]

                                # Extract usage metadata from AI messages
                                # Accumulate across ALL calls (not just the last one)
                                if (
                                    hasattr(last_message, "usage_metadata")
                                    and last_message.usage_metadata
                                ):
                                    meta = last_message.usage_metadata
                                    cumulative_input_tokens += meta.get("input_tokens", 0)
                                    cumulative_output_tokens += meta.get("output_tokens", 0)
                                    cumulative_total_tokens += meta.get("total_tokens", 0)

                                # Check for tool calls
                                if (
                                    hasattr(last_message, "tool_calls")
                                    and last_message.tool_calls
                                ):
                                    for tool_call in last_message.tool_calls:
                                        yield format_sse_event(
                                            "tool_start",
                                            {
                                                "tool_name": tool_call.get("name"),
                                                "tool_id": tool_call.get("id"),
                                                "tool_args": tool_call.get("args", {}),
                                                "node": node_name,
                                            },
                                        )

                                # Check for tool results
                                if hasattr(last_message, "name") and last_message.name:
                                    output_preview = (
                                        str(last_message.content)[:200] + "..."
                                        if len(str(last_message.content)) > 200
                                        else str(last_message.content)
                                    )
                                    yield format_sse_event(
                                        "tool_complete",
                                        {
                                            "tool_name": last_message.name,
                                            "output_preview": output_preview,
                                            "node": node_name,
                                        },
                                    )

                    # Handle LLM token streaming
                    elif stream_mode == "messages":
                        message_chunk, metadata = chunk

                        if metadata is None:
                            continue
                        if model_provider is None and "ls_provider" in metadata:
                            model_provider = metadata["ls_provider"]
                        if model_name is None and "ls_model_name" in metadata:
                            model_name = metadata["ls_model_name"]

                        node_name = metadata.get("langgraph_node", "unknown")

                        if hasattr(message_chunk, "content"):
                            content = message_chunk.content

                            if isinstance(content, str) and content:
                                yield format_sse_event(
                                    "agent_thinking",
                                    {
                                        "token": content,
                                        "node": node_name,
                                    },
                                )

                            elif isinstance(content, list) and content:
                                for block in content:
                                    if isinstance(block, dict):
                                        block_type = block.get("type")

                                        if block_type == "text":
                                            text = block.get("text", "")
                                            if text:
                                                yield format_sse_event(
                                                    "agent_thinking",
                                                    {
                                                        "token": text,
                                                        "node": node_name,
                                                    },
                                                )

                                        elif block_type == "tool_use":
                                            yield format_sse_event(
                                                "tool_calling",
                                                {
                                                    "tool_name": block.get("name"),
                                                    "tool_id": block.get("id"),
                                                    "node": node_name,
                                                },
                                            )

                # Calculate timing
                end_time = datetime.now()
                total_duration = (
                    end_time - start_time
                ).total_seconds() * 1000  # in milliseconds
                first_response_duration = (
                    (first_response_time - start_time).total_seconds() * 1000
                    if first_response_time
                    else None
                )

                # Get final token usage summary from state if available
                final_tokens = {}
                try:
                    config_for_state = {
                        "configurable": {"thread_id": request.project_id}
                    }
                    state = await agent.aget_state(config_for_state)

                    if state and state.values:
                        tokens_data = state.values.get("tokens_used", {})
                        if tokens_data:
                            final_tokens = {
                                "total_input": tokens_data.get("total_input", 0),
                                "total_output": tokens_data.get("total_output", 0),
                                "total_cost": tokens_data.get("total_cost", 0.0),
                                "by_model": tokens_data.get("by_model", {}),
                            }
                except Exception as e:
                    logger.warning(f"Failed to get final token usage: {e}")

                # Send completion event with CUMULATIVE token usage
                cumulative_usage = {
                    "input_tokens": cumulative_input_tokens,
                    "output_tokens": cumulative_output_tokens,
                    "total_tokens": cumulative_total_tokens,
                }

                yield format_sse_event(
                    "agent_complete",
                    {
                        "timestamp": datetime.now().isoformat(),
                        "project_id": request.project_id,
                        "usage_metadata": cumulative_usage,
                        "token_summary": final_tokens,  # Include token summary
                        "model_provider": model_provider,
                        "model_name": model_name,
                        "timing": {
                            "total_duration_ms": round(total_duration, 2),
                            "first_response_ms": (
                                round(first_response_duration, 2)
                                if first_response_duration
                                else None
                            ),
                            "start_time": start_time.isoformat(),
                            "end_time": end_time.isoformat(),
                        },
                    },
                )

                completed_successfully = True

            except UnboundLocalError as e:
                # Handle LangChain internal UnboundLocalError (known edge case bug)
                had_error = True
                error_msg = "An internal error occurred while processing tool responses. This may be due to an unexpected message structure. Please try again."
                logger.error(
                    f"LangChain internal error (UnboundLocalError): {e}", exc_info=True
                )
                logger.warning(
                    "This is a known LangChain edge case bug. Consider retrying the request."
                )
                yield format_sse_event(
                    "error",
                    {
                        "message": error_msg,
                        "type": "LangChainInternalError",
                        "internal_error": str(e),
                        "timestamp": datetime.now().isoformat(),
                        "suggestion": "Please try your request again. If the issue persists, try rephrasing your request.",
                    },
                )
            except Exception as e:
                had_error = True
                logger.error(f"Agent execution error: {e}", exc_info=True)
                yield format_sse_event(
                    "error",
                    {
                        "message": str(e),
                        "type": type(e).__name__,
                        "timestamp": datetime.now().isoformat(),
                    },
                )

            finally:
                # Log stream completion status
                if not completed_successfully and not had_error:
                    logger.info(
                        f"Stream ended for project {request.project_id} "
                        f"(likely user navigation/disconnect)"
                    )

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    finally:
        duration = time.monotonic() - start
        logger.info(f"/chat took {duration:.2f} seconds")


# ========== PROJECT MANAGEMENT ENDPOINTS ==========


@app.post("/projects/history")
async def get_project_history(request: ProjectHistoryRequest):
    """
    Get conversation history for a project.

    Args:
        request: ProjectHistoryRequest containing project_id and limit

    Returns:
        List of checkpoints with messages and metadata

    Example Request:
    ```
    {
        "project_id": "project_456",
        "limit": 50
    }
    ```
    """
    try:
        checkpointer_service = await get_checkpointer_service()

        if not checkpointer_service._initialized:
            raise HTTPException(status_code=503, detail="Checkpointer not initialized")

        history = await checkpointer_service.get_thread_history(
            thread_id=request.project_id, limit=request.limit
        )

        return {
            "project_id": request.project_id,
            "count": len(history),
            "history": history,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/projects/state")
async def get_project_state(request: ProjectStateRequest):
    """
    Get current state for a project.

    Args:
        request: ProjectStateRequest containing project_id

    Returns:
        Current checkpoint state with messages and metadata

    Example Request:
    ```
    {
        "project_id": "project_456"
    }
    ```
    """
    try:
        checkpointer_service = await get_checkpointer_service()

        if not checkpointer_service._initialized:
            raise HTTPException(status_code=503, detail="Checkpointer not initialized")

        state = await checkpointer_service.get_current_state(
            thread_id=request.project_id
        )

        if state is None:
            return {
                "project_id": request.project_id,
                "state": None,
                "message": "No state found for this project",
            }

        return {"project_id": request.project_id, "state": state}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session state: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/projects/delete")
async def delete_project(request: DeleteProjectRequest):
    """
    Delete all history for a project.

    Args:
        request: DeleteProjectRequest containing project_id

    Returns:
        Success status

    Example Request:
    ```
    {
        "project_id": "project_456"
    }
    ```
    """
    try:
        checkpointer_service = await get_checkpointer_service()

        if not checkpointer_service._initialized:
            raise HTTPException(status_code=503, detail="Checkpointer not initialized")

        success = await checkpointer_service.delete_thread_history(
            thread_id=request.project_id
        )

        if success:
            return {
                "project_id": request.project_id,
                "deleted": True,
                "message": "Project history deleted successfully",
            }
        else:
            raise HTTPException(
                status_code=500, detail="Failed to delete session history"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete project: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========== SANDBOX MANAGEMENT ENDPOINTS ==========


@app.get("/api/sandboxes/paused")
async def list_paused_sandboxes():
    """
    List all paused sandboxes.

    Returns:
        List of paused sandboxes with their IDs, states, and metadata
    """
    try:
        from sandbox_manager import list_paused_sandboxes as list_paused_sandboxes_func

        paused_sandboxes = await list_paused_sandboxes_func()

        return {
            "count": len(paused_sandboxes),
            "sandboxes": paused_sandboxes,
        }

    except ValueError as e:
        logger.error(f"Failed to list paused sandboxes: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list paused sandboxes: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
