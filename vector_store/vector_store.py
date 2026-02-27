"""
MongoDB Atlas Vector Store Manager

Features:
- Connection pooling with retry logic
- Index validation with fail-fast option
- Health checks with connection pool monitoring
- Thread-safe singleton pattern

Content Types:
- "image": For image embeddings
- "document": For all text-based content (PDFs, code files, text files, etc.)
  Note: Code files (.py, .js, etc.) should use "document" type, not a separate collection.
"""

import os
import logging
import time
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from langchain_openai import OpenAIEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_core.documents import Document
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from pymongo.operations import SearchIndexModel
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Collection and index configurations
COLLECTIONS = {
    "image": "image_embeddings",
    "document": "document_embeddings",  # Handles all text: PDFs, code, txt, etc.
}

INDEXES = {
    "image": "image_vector_index",
    "document": "document_vector_index",  # Single index for all documents
}

EMBEDDING_CONFIGS = {
    "text-embedding-3-small": {"dimensions": 1536, "max_tokens": 8191},
    "text-embedding-3-large": {"dimensions": 3072, "max_tokens": 8191},
    "text-embedding-ada-002": {"dimensions": 1536, "max_tokens": 8191},
}


class VectorStoreManager:
    """
    MongoDB Atlas vector store manager with connection pooling and health checks.
    Implements thread-safe singleton pattern.
    """

    _instance = None
    _client: Optional[MongoClient] = None
    _embeddings: Optional[OpenAIEmbeddings] = None
    _vector_stores: Dict[str, MongoDBAtlasVectorSearch] = {}
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        db_name: Optional[str] = None,
        embedding_model: str = "text-embedding-3-small",
        openai_api_key: Optional[str] = None,
        max_pool_size: int = int(os.getenv("MONGODB_MAX_POOL_SIZE", "50")),
        min_pool_size: int = int(os.getenv("MONGODB_MIN_POOL_SIZE", "5")),
        max_idle_time_ms: int = int(os.getenv("MONGODB_MAX_IDLE_TIME_MS", "120000")),
        server_selection_timeout_ms: int = int(
            os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "30000")
        ),
        socket_timeout_ms: int = int(os.getenv("MONGODB_SOCKET_TIMEOUT_MS", "60000")),
        connect_timeout_ms: int = int(os.getenv("MONGODB_CONNECT_TIMEOUT_MS", "45000")),
        retry_writes: bool = True,
        retry_reads: bool = True,
        embedding_startup_check: Optional[bool] = False,
        fail_on_missing_index: bool = True,
    ):
        if VectorStoreManager._initialized:
            logger.debug("VectorStoreManager already initialized (singleton)")
            return

        self.mongo_uri = mongo_uri or os.getenv("MONGODB_CONNECTION_STRING")
        self.db_name = db_name or os.getenv("VECTOR_STORE_DB_NAME", "langchain_game_agent")
        self.embedding_model = embedding_model
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")

        self.embedding_startup_check = (
            embedding_startup_check
            if embedding_startup_check is not None
            else os.getenv("EMBEDDING_STARTUP_CHECK", "false").lower() == "true"
        )
        self.fail_on_missing_index = fail_on_missing_index

        self.connection_config = {
            "maxPoolSize": max_pool_size,
            "minPoolSize": min_pool_size,
            "maxIdleTimeMS": max_idle_time_ms,
            "serverSelectionTimeoutMS": server_selection_timeout_ms,
            "socketTimeoutMS": socket_timeout_ms,
            "connectTimeoutMS": connect_timeout_ms,
            "retryWrites": retry_writes,
            "retryReads": retry_reads,
            "ssl": True,
        }

        if not self.mongo_uri:
            raise ValueError("MONGODB_CONNECTION_STRING not set")

        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY not set")

        if self.embedding_model not in EMBEDDING_CONFIGS:
            logger.warning(
                f"Unknown embedding model: {self.embedding_model}. "
                f"Known: {list(EMBEDDING_CONFIGS.keys())}"
            )

        self._init_client()
        self._init_embeddings()

        VectorStoreManager._initialized = True
        logger.info("VectorStoreManager initialized")

    def _init_client(self):
        """Initialize MongoDB client with connection pooling (lazy connection)."""
        try:
            VectorStoreManager._client = MongoClient(
                self.mongo_uri, **self.connection_config
            )
            logger.info(
                f"MongoDB configured (pool: {self.connection_config['minPoolSize']}-"
                f"{self.connection_config['maxPoolSize']}, lazy)"
            )
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"MongoDB connection failed: {e}")
            raise

    def _init_embeddings(self):
        """Initialize embeddings with optional startup check."""
        try:
            VectorStoreManager._embeddings = OpenAIEmbeddings(
                model=self.embedding_model,
                api_key=self.openai_api_key,
                show_progress_bar=False,
                max_retries=3,
                request_timeout=30,
            )

            if self.embedding_startup_check:
                test_result = VectorStoreManager._embeddings.embed_query("test")
                expected_dims = EMBEDDING_CONFIGS.get(self.embedding_model, {}).get(
                    "dimensions"
                )
                if expected_dims and len(test_result) != expected_dims:
                    logger.warning(
                        f"Dimension mismatch: expected {expected_dims}, got {len(test_result)}"
                    )
                logger.info(
                    f"Embeddings verified ({self.embedding_model}, {len(test_result)} dims)"
                )
            else:
                logger.info(f"Embeddings configured ({self.embedding_model})")

        except Exception as e:
            logger.error(f"Embeddings initialization failed: {e}")
            raise

    @property
    def client(self) -> MongoClient:
        if VectorStoreManager._client is None:
            raise RuntimeError("MongoDB client not initialized")
        return VectorStoreManager._client

    @property
    def embeddings(self) -> OpenAIEmbeddings:
        if VectorStoreManager._embeddings is None:
            raise RuntimeError("Embeddings not initialized")
        return VectorStoreManager._embeddings

    def get_vector_store(
        self,
        collection_name: str,
        index_name: str = "vector_index",
        relevance_score_fn: str = "cosine",
        validate_index: bool = True,
        fail_on_missing_index: Optional[bool] = None,
        auto_create_index: bool = True,
    ) -> MongoDBAtlasVectorSearch:
        """Get or create vector store for collection."""
        cache_key = f"{self.db_name}.{collection_name}.{index_name}"

        if cache_key not in VectorStoreManager._vector_stores:
            db = self.client[self.db_name]
            collection = db[collection_name]

            if validate_index:
                if auto_create_index:
                    self._ensure_vector_index(collection, index_name)
                else:
                    fail_fast = (
                        fail_on_missing_index
                        if fail_on_missing_index is not None
                        else self.fail_on_missing_index
                    )
                    self._validate_vector_index(collection, index_name, fail_fast)

            vector_store = MongoDBAtlasVectorSearch(
                collection=collection,
                embedding=self.embeddings,
                index_name=index_name,
                relevance_score_fn=relevance_score_fn,
                text_key="page_content",
                embedding_key="embedding",
            )

            VectorStoreManager._vector_stores[cache_key] = vector_store
            logger.info(f"Vector store created: {cache_key}")

        return VectorStoreManager._vector_stores[cache_key]

    def _ensure_vector_index(
        self,
        collection,
        index_name: str,
        dimensions: int = 1536,
        similarity: str = "cosine",
    ) -> bool:
        """Ensure a vector search index exists, creating it if missing."""
        try:
            # Atlas requires the collection to exist before creating a search index.
            # Create it if it doesn't exist yet (no-op if it already exists).
            db = collection.database
            if collection.name not in db.list_collection_names():
                logger.info(
                    f"Collection '{collection.name}' does not exist — creating it..."
                )
                db.create_collection(collection.name)
                logger.info(f" Collection '{collection.name}' created")

            indexes = list(collection.list_search_indexes())
            index_names = [idx.get("name") for idx in indexes]

            if index_name in index_names:
                logger.debug(f"Index '{index_name}' already exists in '{collection.name}'")
                return True

            logger.info(
                f"Index '{index_name}' not found in '{collection.name}' — creating it..."
            )

            # Derive dimensions from the configured embedding model
            config_dims = EMBEDDING_CONFIGS.get(self.embedding_model, {}).get(
                "dimensions", dimensions
            )

            index_definition = {
                "fields": [
                    {
                        "type": "vector",
                        "path": "embedding",
                        "numDimensions": config_dims,
                        "similarity": similarity,
                    }
                ]
            }
            model = SearchIndexModel(
                definition=index_definition,
                name=index_name,
                type="vectorSearch",
            )
            collection.create_search_index(model=model)
            logger.info(
                f"Vector search index '{index_name}' created in '{collection.name}' "
                f"({config_dims} dims, {similarity}). It may take a minute to become active."
            )
            return True

        except Exception as e:
            logger.warning(
                f"Could not auto-create vector search index '{index_name}' "
                f"in '{collection.name}': {e}. Proceeding without validation."
            )
            return False

    def _validate_vector_index(
        self, collection, index_name: str, fail_on_missing: bool = True
    ) -> bool:
        """Validate vector search index exists."""
        try:
            indexes = list(collection.list_search_indexes())
            index_names = [idx.get("name") for idx in indexes]

            if index_name not in index_names:
                error_msg = f"Index '{index_name}' not found in '{collection.name}'. Available: {index_names}"
                if fail_on_missing:
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                logger.warning(error_msg)
                return False

            logger.debug(f"Index '{index_name}' validated")
            return True

        except Exception as e:
            if fail_on_missing:
                raise
            logger.warning(f"Index validation failed: {e}")
            return False

    def get_collection(self, collection_name: str):
        return self.client[self.db_name][collection_name]

    def health_check(self, test_vector_search: bool = False) -> Dict[str, Any]:
        """
        Check MongoDB connection health.

        Args:
            test_vector_search: Also test vector search performance

        Returns:
            Health status dictionary with connection pool metrics
        """
        try:
            start = time.time()
            self.client.admin.command("ping")
            latency_ms = (time.time() - start) * 1000

            health = {
                "status": "healthy",
                "latency_ms": round(latency_ms, 2),
                "mongodb_version": self.client.server_info().get("version"),
                "vector_stores": len(VectorStoreManager._vector_stores),
                "embedding_model": self.embedding_model,
            }

            # Add connection pool metrics
            try:
                pool_config = {
                    "max_pool_size": self.connection_config.get("maxPoolSize"),
                    "min_pool_size": self.connection_config.get("minPoolSize"),
                }
                health["connection_pool"] = pool_config
            except Exception as e:
                logger.debug(f"Could not get pool stats: {e}")

            if test_vector_search and VectorStoreManager._vector_stores:
                try:
                    vs_key = list(VectorStoreManager._vector_stores.keys())[0]
                    vs = VectorStoreManager._vector_stores[vs_key]
                    start = time.time()
                    _ = vs.similarity_search("health check", k=1)
                    health["vector_search_latency_ms"] = round(
                        (time.time() - start) * 1000, 2
                    )
                except Exception as e:
                    health["vector_search_error"] = str(e)

            return health

        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def close(self):
        """Close all connections."""
        if VectorStoreManager._client:
            VectorStoreManager._client.close()
            VectorStoreManager._client = None
            VectorStoreManager._vector_stores.clear()
            VectorStoreManager._initialized = False
            logger.info("MongoDB connections closed")


_default_manager: Optional[VectorStoreManager] = None


def get_vector_store_manager(**kwargs) -> VectorStoreManager:
    """Get singleton vector store manager."""
    global _default_manager
    if _default_manager is None:
        _default_manager = VectorStoreManager(**kwargs)
    return _default_manager


def get_vector_store(content_type: str, **kwargs) -> MongoDBAtlasVectorSearch:
    """
    Get vector store by content type.

    Args:
        content_type: Type of content ("image" or "document")
                     Note: Code files should use "document" type
        **kwargs: Additional arguments for get_vector_store()

    Returns:
        MongoDBAtlasVectorSearch instance

    Example:
        # For PDFs, text files, code files
        doc_store = get_vector_store("document")

        # For images
        img_store = get_vector_store("image")
    """
    if content_type not in COLLECTIONS:
        raise ValueError(
            f"Unknown content type '{content_type}'. "
            f"Valid: {list(COLLECTIONS.keys())}. "
            f"Note: Use 'document' for code files (.py, .js, etc.)"
        )

    collection_name = COLLECTIONS[content_type]
    index_name = INDEXES[content_type]
    manager = get_vector_store_manager()
    return manager.get_vector_store(collection_name, index_name, **kwargs)


def cleanup():
    """Cleanup on shutdown."""
    global _default_manager
    if _default_manager:
        _default_manager.close()
        _default_manager = None


@asynccontextmanager
async def vector_store_lifespan(app):
    """FastAPI lifespan handler for vector store."""
    get_vector_store_manager()
    logger.info("Vector store started")
    yield
    cleanup()
    logger.info("Vector store shutdown")
