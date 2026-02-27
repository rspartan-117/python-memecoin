import logging
import asyncio
import os
import ssl
import time
from typing import Optional, Dict, Any, List
from langgraph.checkpoint.mongodb.aio import AsyncMongoDBSaver
from langgraph.store.mongodb import MongoDBStore, create_vector_index_config
from langchain_openai import OpenAIEmbeddings
from pymongo.asynchronous.mongo_client import AsyncMongoClient
from pymongo import MongoClient  # Synchronous client for MongoDBStore
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, AutoReconnect
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Prefer certifi's CA bundle for secure TLS verification when available.
try:
    import certifi

    _CERTIFI_CA = certifi.where()
except Exception:
    _CERTIFI_CA = None

# Global embeddings instance (singleton for reuse across service instances)
_global_embeddings: Optional[OpenAIEmbeddings] = None
_embeddings_lock = asyncio.Lock()
_embeddings_initializing = False


def _parse_boolean(value: str) -> bool:
    """Robust boolean parsing from environment variables."""
    if not value:
        return False
    value_lower = str(value).lower().strip()
    return value_lower in ("true", "1", "yes", "on", "enabled")


async def get_embeddings() -> OpenAIEmbeddings:
    """
    Get or create global embeddings instance (thread-safe singleton pattern).
    This function is async to support proper lock usage in async contexts.
    """
    global _global_embeddings, _embeddings_initializing

    if _global_embeddings is not None:
        return _global_embeddings

    # Thread-safe initialization with asyncio lock
    async with _embeddings_lock:
        # Double-check pattern after acquiring lock
        if _global_embeddings is not None:
            return _global_embeddings

        if _embeddings_initializing:
            # Another coroutine is initializing, wait and retry
            await asyncio.sleep(0.1)
            return await get_embeddings()

        _embeddings_initializing = True
        try:
            logger.info("[EMBEDDINGS] Creating global OpenAI embeddings instance...")
            _global_embeddings = OpenAIEmbeddings(
                model="text-embedding-3-small",  # Fast & cost-effective (1536 dims)
                openai_api_key=os.getenv("OPENAI_API_KEY"),
            )
            logger.info(
                "✅ Global embeddings instance created (text-embedding-3-small)"
            )
            return _global_embeddings
        finally:
            _embeddings_initializing = False


async def _retry_mongodb_operation(
    operation,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    backoff_factor: float = 2.0,
):
    """
    Retry MongoDB operations with exponential backoff.

    Args:
        operation: Async callable to retry
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        backoff_factor: Multiplier for exponential backoff
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except (ConnectionFailure, ServerSelectionTimeoutError, AutoReconnect) as e:
            last_exception = e
            if attempt < max_retries:
                delay = min(initial_delay * (backoff_factor**attempt), max_delay)
                logger.warning(
                    f"MongoDB operation failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                    f"Retrying in {delay:.2f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"MongoDB operation failed after {max_retries + 1} attempts: {e}"
                )
        except Exception as e:
            # Non-retryable exceptions
            logger.error(f"MongoDB operation failed with non-retryable error: {e}")
            raise

    raise last_exception


class CheckpointerService:
    """
    Production MongoDB checkpointer + store service.
    Handles:
    - Message history persistence (automatic)
    - State checkpoints
    - Thread management
    - Long-term memory storage (MongoDBStore)
    - Connection lifecycle (shared client for both)
    """

    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        db_name: str = "checkpointing_db",
        checkpoint_collection: str = "checkpoints",
        writes_collection: str = "checkpoint_writes",
        store_collection: str = "memories",
        ttl: Optional[int] = None,
        memory_ttl: Optional[int] = None,
        enable_semantic_search: bool = True,
    ):
        self.mongo_uri = (
            mongo_uri or os.getenv("MONGODB_CONNECTION_STRING") or os.getenv("DATABASE_URL")
        )
        self.db_name = db_name
        self.checkpoint_collection = checkpoint_collection
        self.writes_collection = writes_collection
        self.store_collection = store_collection
        self.ttl = ttl
        # Memory TTL configurable via environment variable
        self.memory_ttl = memory_ttl or (
            int(os.getenv("MONGODB_MEMORY_TTL"))
            if os.getenv("MONGODB_MEMORY_TTL")
            else None
        )
        self.enable_semantic_search = enable_semantic_search
        self.client: Optional[AsyncMongoClient] = None  # Async client for checkpointer
        self.sync_client: Optional[MongoClient] = None  # Sync client for store
        self.checkpointer: Optional[AsyncMongoDBSaver] = None
        self.store: Optional[MongoDBStore] = None
        self._embeddings: Optional[OpenAIEmbeddings] = None
        self._initialized = False

    async def initialize(self):
        """Initialize checkpointer with MongoDB client"""
        if self._initialized:
            logger.info("✅ Checkpointer already initialized")
            return

        try:
            logger.info("[CHECKPOINTER] Initializing MongoDB connection...")

            # Initialize global embeddings first (if semantic search enabled)
            if self.enable_semantic_search:
                logger.info(
                    "[EMBEDDINGS] Pre-initializing global embeddings instance..."
                )
                self._embeddings = await get_embeddings()
                logger.info("✅ Embeddings ready for use")

            # Get MongoDB URI from environment if not set
            if self.mongo_uri is None:
                raise ValueError("MONGODB_CONNECTION_STRING not found in environment")

            logger.info(f"[CHECKPOINTER] MONGODB_CONNECTION_STRING {self.mongo_uri[:30]}...")

            # Create MongoDB client
            logger.info("[CHECKPOINTER] Creating MongoDB client...")

            client_kwargs: Dict[str, Any] = {
                "maxPoolSize": 50,
                "minPoolSize": 10,
                "serverSelectionTimeoutMS": 5000,
                "connectTimeoutMS": 10000,
                "socketTimeoutMS": 30000,
                "retryWrites": True,
                "retryReads": True,
            }

            if _CERTIFI_CA:
                # Use certifi CA bundle for proper certificate verification
                client_kwargs["tls"] = True
                client_kwargs["tlsCAFile"] = _CERTIFI_CA
                logger.info(
                    "[CHECKPOINTER] Using certifi CA bundle for TLS verification"
                )
            else:
                # Development fallback: allow invalid certificates (insecure)
                client_kwargs["tls"] = True
                client_kwargs["tlsAllowInvalidCertificates"] = True
                client_kwargs["tlsAllowInvalidHostnames"] = True
                logger.warning(
                    "[CHECKPOINTER] certifi not found — using insecure TLS fallback. "
                    "Install 'certifi' (pip install certifi) for secure connections."
                )

            # Create clients with retry logic
            async def _create_async_client():
                self.client = AsyncMongoClient(self.mongo_uri, **client_kwargs)
                # Test async connection
                await self.client.admin.command("ping")
                return self.client

            logger.info("[CHECKPOINTER] Creating MongoDB async client with retry...")
            await _retry_mongodb_operation(_create_async_client)
            logger.info("✅ MongoDB async connection successful")

            # Create synchronous client for MongoDBStore (it doesn't support async)
            logger.info(
                "[CHECKPOINTER] Creating synchronous MongoDB client for store..."
            )
            # Sync client creation (retry handled by pymongo internally)
            self.sync_client = MongoClient(self.mongo_uri, **client_kwargs)

            # Test sync connection with retry
            async def _test_sync_connection():
                self.sync_client.admin.command("ping")
                return True

            await _retry_mongodb_operation(_test_sync_connection)
            logger.info("✅ MongoDB sync connection successful")

            # Create checkpointer with setup
            logger.info(
                "[CHECKPOINTER] Creating checkpointer and setting up collections..."
            )
            self.checkpointer = AsyncMongoDBSaver(
                client=self.client,
                db_name=self.db_name,
                checkpoint_collection_name=self.checkpoint_collection,
                writes_collection_name=self.writes_collection,
                ttl=self.ttl,
            )

            # The checkpointer handles setup automatically.
            await self.checkpointer._setup()
            logger.info("✅ AsyncMongoDBSaver created and indexes setup complete")

            # Index verification commented out - indexes are handled internally by checkpointer
            # async def _verify_indexes():
            #     db = self.client[self.db_name]
            #     checkpoint_col = db[self.checkpoint_collection]
            #     indexes = await checkpoint_col.list_indexes().to_list(length=None)
            #     index_names = [idx["name"] for idx in indexes]
            #     required_indexes = ["thread_id_1", "thread_id_1_parent_id_1"]
            #     missing_indexes = [idx for idx in required_indexes if idx not in index_names]
            #     if missing_indexes:
            #         logger.warning(
            #             f"⚠️ Some checkpoint indexes may be missing: {missing_indexes}. "
            #             "The checkpointer should create them automatically on first write."
            #         )
            #     else:
            #         logger.info("✅ Checkpoint collection indexes verified")
            # try:
            #     await _retry_mongodb_operation(_verify_indexes)
            # except Exception as e:
            #     logger.warning(f"⚠️ Could not verify indexes (will be created on first write): {e}")

            # Create MongoDBStore (uses synchronous client)
            logger.info("[CHECKPOINTER] Creating MongoDBStore (sync client)...")
            db = self.sync_client[self.db_name]
            store_collection = db[self.store_collection]

            # Configure vector index for semantic search if enabled
            index_config = None
            if self.enable_semantic_search:
                logger.info(
                    "[STORE] Setting up semantic search with OpenAI embeddings..."
                )
                # Reuse global embeddings instance (singleton)
                self._embeddings = await get_embeddings()
                index_config = create_vector_index_config(
                    dims=1536,  # text-embedding-3-small dimensions
                    embed=self._embeddings,
                    fields=["content"],  # Index the content field
                    name="memory_vector_index",  # MongoDB Atlas index name
                    relevance_score_fn="cosine",  # Cosine similarity
                    embedding_key="embedding",  # Field to store embeddings
                    filters=["namespace"],  # Enable namespace filtering
                )
                logger.info(
                    "✅ Vector index config created (cosine similarity, 1536 dims)"
                )

            # Configure TTL for memory store (configurable)
            ttl_config = None
            if self.memory_ttl:
                ttl_config = {"seconds": self.memory_ttl}
                logger.info(f"[STORE] Memory TTL configured: {self.memory_ttl} seconds")

            self.store = MongoDBStore(
                collection=store_collection,
                ttl_config=ttl_config,  # Configurable TTL for memories
                index_config=index_config,  # Enable semantic search if configured
            )

            if self.enable_semantic_search:
                logger.info("✅ MongoDBStore created with semantic search enabled")

                # Vector index verification commented out - indexes are handled internally by MongoDBStore
                # logger.info("[STORE] Verifying vector index exists...")
                # try:
                #     db = self.sync_client[self.db_name]
                #     collection = db[self.store_collection]
                #     indexes = collection.list_indexes()
                #     index_names = [idx["name"] for idx in indexes]
                #     vector_index_name = "memory_vector_index"
                #     if vector_index_name in index_names:
                #         logger.info(f"✅ Vector index '{vector_index_name}' verified")
                #     else:
                #         logger.warning(
                #             f"⚠️ Vector index '{vector_index_name}' not found. "
                #             "It will be created automatically on first semantic search operation."
                #         )
                # except Exception as e:
                #     logger.warning(f"⚠️ Could not verify vector index: {e}. It will be created on first use.")
            else:
                logger.info(
                    "✅ MongoDBStore created (key-value only, no semantic search)"
                )

            self._initialized = True
            logger.info("✅ Checkpointer + Store fully initialized and ready")

        except Exception as e:
            logger.error(f"❌ Checkpointer initialization failed: {e}", exc_info=True)
            # Cleanup on failure
            if self.client:
                try:
                    await self.client.close()
                except Exception:
                    pass
            if self.sync_client:
                try:
                    self.sync_client.close()
                except Exception:
                    pass
            raise

    async def close(self):
        """Close checkpointer + store connections gracefully"""
        if self.client:
            try:
                await self.client.close()
                logger.info("✅ MongoDB async client closed")
            except Exception as e:
                logger.error(f"Error closing async MongoDB client: {e}")

        if self.sync_client:
            try:
                self.sync_client.close()
                logger.info("✅ MongoDB sync client closed")
            except Exception as e:
                logger.error(f"Error closing sync MongoDB client: {e}")

        self._initialized = False
        logger.info("✅ Checkpointer + Store shutdown complete")

    def get_checkpointer(
        self,
    ) -> AsyncMongoDBSaver:
        """Get the checkpointer instance"""
        if not self._initialized:
            raise RuntimeError(
                "Checkpointer not initialized. "
                "Call await checkpointer_service.initialize() first."
            )

        return self.checkpointer

    def get_store(self) -> MongoDBStore:
        """Get the store instance (shares same MongoDB client)"""
        if not self._initialized or not self.store:
            raise RuntimeError(
                "Store not initialized. "
                "Call await checkpointer_service.initialize() first."
            )

        return self.store

    def get_embeddings(self) -> Optional[OpenAIEmbeddings]:
        """Get the embeddings instance (only available if semantic search is enabled)."""
        if not self._initialized:
            raise RuntimeError(
                "Service not initialized. "
                "Call await checkpointer_service.initialize() first."
            )

        if not self.enable_semantic_search:
            logger.warning("Semantic search is disabled. No embeddings available.")
            return None

        return self._embeddings

    async def health_check(self) -> Dict[str, Any]:
        """Check checkpointer + store health"""
        if not self._initialized or not self.client:
            return {
                "status": "not_initialized",
                "message": "Checkpointer + Store not initialized",
            }

        try:
            # Ping MongoDB with retry
            async def _ping():
                await self.client.admin.command("ping")
                return True

            await _retry_mongodb_operation(_ping, max_retries=2)

            health_info: Dict[str, Any] = {
                "status": "healthy",
                "database": self.db_name,
                "checkpoint_collection": self.checkpoint_collection,
                "writes_collection": self.writes_collection,
                "store_collection": self.store_collection,
                "semantic_search": self.enable_semantic_search,
                "connection": "shared_pool",
            }

            # Add TTL info if configured
            if self.memory_ttl:
                health_info["memory_ttl_seconds"] = self.memory_ttl

            return health_info
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    async def get_thread_history(
        self, thread_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get conversation history for a thread (project)"""
        if not self._initialized:
            raise RuntimeError("Checkpointer not initialized")

        try:
            config = {"configurable": {"thread_id": thread_id}}

            # Get state history with retry
            async def _get_history():
                history: List[Dict[str, Any]] = []
                try:
                    async for checkpoint_tuple in self.checkpointer.alist(
                        config=config,
                        limit=limit,
                    ):
                        # ✅ CORRECT: Access CheckpointTuple attributes directly
                        checkpoint = checkpoint_tuple.checkpoint
                        metadata = checkpoint_tuple.metadata or {}
                        
                        # The checkpoint dict structure:
                        # checkpoint = {
                        #     'v': 3,
                        #     'ts': '2025-05-05T16:01:24.680462+00:00',
                        #     'id': 'checkpoint-id',
                        #     'channel_values': {'messages': [...]},
                        #     'channel_versions': {...},
                        #     'versions_seen': {...}
                        # }
                        
                        # Messages are in checkpoint['channel_values']['messages']
                        channel_values = checkpoint.get("channel_values", {})
                        messages = channel_values.get("messages", [])
                        
                        history.append(
                            {
                                "checkpoint_id": checkpoint.get("id"),
                                "timestamp": checkpoint.get("ts"),
                                "messages": messages,
                                "metadata": metadata,
                            }
                        )
                except StopAsyncIteration:
                    pass  # Normal end of iteration
                
                return history

            history = await _retry_mongodb_operation(_get_history)
            logger.info(f"✓ Retrieved {len(history)} checkpoints for thread {thread_id}")
            return history

        except Exception as e:
            logger.error(f"✗ Failed to get thread history: {e}", exc_info=True)
            return []

    async def get_current_state(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Get current state for a thread"""
        if not self._initialized:
            raise RuntimeError("Checkpointer not initialized")

        try:
            config = {"configurable": {"thread_id": thread_id}}

            # Get current state with retry
            async def _get_state():
                # aget_tuple() returns CheckpointTuple
                checkpoint_tuple = await self.checkpointer.aget_tuple(config)
                if checkpoint_tuple:
                    checkpoint = checkpoint_tuple.checkpoint
                    metadata = checkpoint_tuple.metadata or {}
                    
                    # Messages are in checkpoint['channel_values']['messages']
                    channel_values = checkpoint.get("channel_values", {})
                    messages = channel_values.get("messages", [])
                    
                    return {
                        "checkpoint_id": checkpoint.get("id"),
                        "timestamp": checkpoint.get("ts"),
                        "messages": messages,
                        "metadata": metadata,
                    }
                return None

            return await _retry_mongodb_operation(_get_state)

        except Exception as e:
            logger.error(f"✗ Failed to get current state: {e}", exc_info=True)
            return None

    async def delete_thread_history(self, thread_id: str) -> bool:
        """
        Delete all history for a thread.
        Use when:
        - Project is deleted
        - User wants to clear conversation
        """
        try:
            # Use MongoDB's native delete method with retry
            async def _delete_thread():
                await self.checkpointer.adelete_thread(thread_id)
                return True

            await _retry_mongodb_operation(_delete_thread)
            logger.info(f"✅ Deleted all checkpoints for thread: {thread_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete thread history: {e}")
            return False


# Global singleton instance with thread-safe initialization
_checkpointer_service: Optional[CheckpointerService] = None
_service_lock = asyncio.Lock()


async def get_checkpointer_service() -> CheckpointerService:
    """
    Get or create the global checkpointer service (thread-safe singleton).
    """
    global _checkpointer_service

    if _checkpointer_service is not None:
        return _checkpointer_service

    async with _service_lock:
        # Double-check pattern for thread safety
        if _checkpointer_service is None:
            _checkpointer_service = CheckpointerService(
                db_name=os.getenv("MONGODB_DB_NAME", "checkpointing_db"),
                checkpoint_collection=os.getenv(
                    "MONGODB_CHECKPOINT_COLLECTION", "checkpoints"
                ),
                writes_collection=os.getenv(
                    "MONGODB_WRITES_COLLECTION", "checkpoint_writes"
                ),
                store_collection=os.getenv("MONGODB_STORE_COLLECTION", "memories"),
                ttl=int(os.getenv("MONGODB_TTL")) if os.getenv("MONGODB_TTL") else None,
                memory_ttl=(
                    int(os.getenv("MONGODB_MEMORY_TTL"))
                    if os.getenv("MONGODB_MEMORY_TTL")
                    else None
                ),
                enable_semantic_search=_parse_boolean(
                    os.getenv("ENABLE_SEMANTIC_SEARCH", "true")
                ),
            )
            logger.info("✅ Checkpointer + Store service singleton created")

        return _checkpointer_service


# Backward compatibility - use singleton pattern instead of creating separate instance
# This prevents resource leaks from duplicate connections
async def get_checkpointer_service_instance() -> CheckpointerService:
    """
    Get the singleton checkpointer service instance.
    This replaces the old 'checkpointer_service' global variable to prevent resource leaks.
    """
    return await get_checkpointer_service()


# Backward compatibility removed to prevent resource leaks
# Use get_checkpointer_service() instead to get the singleton instance
# This prevents duplicate MongoDB connections and memory leaks
#
# Migration guide:
# OLD: checkpointer_service = CheckpointerService(...)
# NEW: checkpointer_service = await get_checkpointer_service()
#
# The singleton pattern ensures only one instance exists with shared connections
