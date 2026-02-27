"""
Vector Store Module

Provides MongoDB Atlas vector store management with connection pooling,
health checks, and easy access to vector stores by content type.
"""

from .vector_store import (
    VectorStoreManager,
    get_vector_store_manager,
    get_vector_store,
    cleanup,
    vector_store_lifespan,
    COLLECTIONS,
    INDEXES,
    EMBEDDING_CONFIGS,
)

__all__ = [
    "VectorStoreManager",
    "get_vector_store_manager",
    "get_vector_store",
    "cleanup",
    "vector_store_lifespan",
    "COLLECTIONS",
    "INDEXES",
    "EMBEDDING_CONFIGS",
]
