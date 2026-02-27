# db/db_manager.py - Production-Ready Database Session Management
"""
Production database connection and SQLAlchemy session factory management
with comprehensive error handling, monitoring, and resilience patterns.

Notes:
- Uses QueuePool (default SQLAlchemy pool) to keep persistent connections warm.
- Keeps asyncpg prepared-statement collisions disabled (for Supavisor).
- Provides startup warm-up and optional keep-alive task to reduce Neon cold-starts.
"""
import asyncio
import uuid
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, Dict, Any
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncEngine,
)
from sqlalchemy.pool import NullPool, Pool
from sqlalchemy.exc import OperationalError, TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy import text

from .config import get_db_settings

# Configure logging
logger = logging.getLogger(__name__)


# Global engine and session factory (singleton pattern)
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None
_init_lock = asyncio.Lock()

# Keep-alive task to prevent Neon scale-to-zero (optional)
_keepalive_task: Optional[asyncio.Task] = None
_keepalive_stop = False


async def init_db(
    use_direct: bool = False, warm: bool = True, enable_keepalive: bool = False
) -> AsyncEngine:
    """
    Initialize the async SQLAlchemy engine and session factory.

    Args:
        use_direct: If True, use direct DB connection settings (port 5432).
                    If False, use pooled endpoint (pooler/neon) — recommended for Neon.
        warm: If True, perform a lightweight warmup (SELECT 1) after opening connections.
        enable_keepalive: If True, start a background task to periodically ping DB to keep it warm.

    Returns:
        AsyncEngine: Initialized SQLAlchemy async engine

    Raises:
        ValueError, OperationalError
    """
    global _engine, _session_factory, _keepalive_task, _keepalive_stop

    # Thread-safe initialization with async lock
    async with _init_lock:
        # Return existing engine if already initialized (singleton)
        if _engine is not None:
            logger.info("✓ Database already initialized, reusing existing engine")
            return _engine

        logger.info("INFO: Initializing database connection...")
        settings = get_db_settings()

        masked_config = settings.mask_sensitive_data()
        logger.info(
            f"[DB INIT] environment={masked_config['ENV']}, mode={'direct' if use_direct else 'pooled'}"
        )

        try:
            # Build connection URL with SSL and timeout parameters
            connection_url = settings.get_connection_url(use_direct=use_direct)
            logger.info("✓ Connection URL built successfully")
        except ValueError as e:
            logger.error(f"Failed to build connection URL: {e}")
            raise

        # asyncpg / SQLAlchemy connect args (Supavisor-friendly)
        connect_args: Dict[str, Any] = {
            # disable statement caches to avoid prepared-statement collisions across pooled connections
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            # generate unique prepared statement names to avoid collisions when reusing connections
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4().hex[:16]}__",
            # timeouts (seconds)
            "timeout": getattr(settings, "CONNECT_TIMEOUT", 10),
            "command_timeout": getattr(settings, "COMMAND_TIMEOUT", 60),
            # server_settings passed on connect (milliseconds for statement_timeout)
            "server_settings": {
                "application_name": f"app_{settings.ENV}",
                "statement_timeout": str(
                    int(getattr(settings, "COMMAND_TIMEOUT", 60) * 1000)
                ),
            },
        }

        # Pool strategy:
        # Use SQLAlchemy's QueuePool (default) for persistent warm connections.
        # Do NOT use NullPool for web APIs talking to Neon.
        poolclass = None  # None = QueuePool (the recommended behavior)

        pool_size = getattr(settings, "POOL_SIZE", 5)
        max_overflow = getattr(settings, "MAX_OVERFLOW", 10)
        pool_timeout = getattr(settings, "POOL_TIMEOUT", 30)
        pool_recycle = getattr(settings, "POOL_RECYCLE", 1800)
        # Build engine configuration
        engine_kwargs: Dict[str, Any] = {
            "echo": bool(getattr(settings, "ECHO_SQL", False)),
            "echo_pool": bool(getattr(settings, "ECHO_POOL", False)),
            "pool_pre_ping": bool(getattr(settings, "POOL_PRE_PING", True)),
            "poolclass": poolclass,
            "connect_args": connect_args,
            # Ensure pooling is enabled for BOTH direct and pooler endpoints
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "pool_timeout": pool_timeout,
            "pool_recycle": pool_recycle,
        }

        try:
            _engine = create_async_engine(connection_url, **engine_kwargs)
            logger.info("✓ Database engine created")

            # Create session factory
            _session_factory = async_sessionmaker(
                _engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )
            logger.info("✓ Session factory created")

            # Optional warmup - run a lightweight query to ensure connection(s) are established
            if warm:
                await warm_connections()
                logger.info("✓ Warmed DB connections")

            # Optional keepalive task to avoid Neon scale-to-zero between requests
            if enable_keepalive:
                if _keepalive_task is None:
                    _keepalive_stop = False
                    _keepalive_task = asyncio.create_task(
                        _keepalive_worker(interval_seconds=120)
                    )
                    logger.info("✓ Keep-alive task started")

            return _engine

        except OperationalError as e:
            logger.error(f"[DB INIT] OperationalError creating engine: {e}")
            raise
        except Exception as e:
            logger.error(f"[DB INIT] Unexpected error creating engine: {e}")
            raise


async def warm_connections():
    """
    Warm DB connections by acquiring a connection and executing a trivial query.
    Useful to prevent Neon cold-start latency for the first real request.
    """
    global _engine
    if _engine is None:
        logger.debug("[DB WARM] Engine not initialized, calling init_db()")
        await init_db()

    try:
        async with _engine.connect() as conn:
            # Use a short statement; this will force the driver to establish the TCP/SSL connection
            await conn.execute(text("SELECT 1"))
            # Don't commit - read-only
    except Exception as e:
        logger.warning(f"[DB WARM] warm_connections failed: {e}")


async def _keepalive_worker(interval_seconds: int = 120):
    """
    Background task pinging the DB periodically to keep connections alive and avoid Neon scale-to-zero.
    It will run until close_db() cancels/clears it.
    """
    global _keepalive_stop, _engine
    logger.info(f"[DB KEEPALIVE] started, interval={interval_seconds}s")
    try:
        while not _keepalive_stop:
            try:
                if _engine is None:
                    await asyncio.sleep(interval_seconds)
                    continue
                async with _engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                logger.debug("[DB KEEPALIVE] ping successful")
            except Exception as e:
                logger.debug(f"[DB KEEPALIVE] ping failed: {e}")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("[DB KEEPALIVE] cancelled")
    finally:
        logger.info("[DB KEEPALIVE] stopped")


async def get_engine() -> AsyncEngine:
    """
    Get or lazily initialize database engine.

    Returns:
        AsyncEngine: Database engine instance
    """
    if _engine is None:
        await init_db()
    return _engine


def get_session_factory() -> async_sessionmaker:
    """
    Get session factory (engine must be initialized first).

    Returns:
        async_sessionmaker: Session factory for creating database sessions

    Raises:
        RuntimeError: If database not initialized
    """
    if _session_factory is None:
        raise RuntimeError(
            "Database not initialized. Call init_db() first, "
            "or use get_db_session() which initializes automatically."
        )
    return _session_factory


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Production context manager for DATABASE sessions (SQLAlchemy).
    NOT related to application sessions (those are now Project records).

    Provides automatic transaction management:
    - Commits on success
    - Rolls back on exceptions
    - Always closes session to release connections

    Use this in your tools for database operations.

    Example:
        async with get_db_session() as session:
            repo = FileRepository(session)
            file = await repo.save_project_file(...)
            # Automatically commits here if no exception

    Yields:
        AsyncSession: Database session for queries and transactions

    Raises:
        OperationalError: If database connection fails
        SQLAlchemyTimeoutError: If query exceeds timeout
    """
    # Lazy initialization - ensure database is ready
    if _session_factory is None:
        await init_db()

    # Create new session from factory
    async with _session_factory() as session:
        try:
            # Yield session for use in 'async with' block
            yield session

            # If no exception occurred, commit all pending changes
            await session.commit()
            logger.debug("Database session committed successfully")

        except (OperationalError, SQLAlchemyTimeoutError) as e:
            # Database-specific errors (connection, timeout, etc.)
            await session.rollback()
            logger.error(
                f"Database error, transaction rolled back: {type(e).__name__}: {e}"
            )
            raise

        except Exception as e:
            # Any other exception - rollback to maintain data integrity
            await session.rollback()
            logger.error(
                f"Unexpected error, transaction rolled back: {type(e).__name__}: {e}"
            )
            raise

        finally:
            # Always close session to release connection back to pool
            # Critical for preventing connection leaks
            await session.close()
            logger.debug("Database session closed")


async def health_check() -> bool:
    """
    Check database connectivity for health monitoring.

    Use this in your application startup or health check endpoints
    to verify database is accessible.

    Returns:
        bool: True if database is healthy, False otherwise

    Example:
        if not await health_check():
            logger.error("Database health check failed!")
    """
    try:
        if _engine is None:
            await init_db()

        # Simple connectivity test
        from sqlalchemy import text

        async with _engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            await result.fetchone()

        logger.info("✓ Database health check passed")
        return True

    except Exception as e:
        logger.error(f"✗ Database health check failed: {e}")
        return False


async def close_db():
    """
    Gracefully close database connections and cleanup resources.

    Call this during application shutdown to ensure clean termination.

    Example:
        @app.on_event("shutdown")
        async def shutdown():
            await close_db()
    """
    global _engine, _session_factory, _keepalive_task, _keepalive_stop

    # Cancel keepalive task first
    if _keepalive_task is not None:
        _keepalive_stop = True
        _keepalive_task.cancel()
        try:
            await _keepalive_task
        except asyncio.CancelledError:
            pass
        _keepalive_task = None
        logger.info("✓ Keepalive task cancelled")

    if _engine:
        logger.info("Closing database connections...")

        try:
            # Dispose of engine - closes all pooled connections
            await _engine.dispose()
            logger.info("✓ Database connections closed successfully")
        except Exception as e:
            logger.error(f"Error during database shutdown: {e}")
        finally:
            # Reset globals to allow re-initialization if needed
            _engine = None
            _session_factory = None


async def get_pool_status() -> dict:
    """
    Get connection pool status for monitoring.

    Returns:
        dict: Pool statistics including size, checked_out connections, etc.
        Returns empty dict if using NullPool (Supavisor mode)

    Example:
        status = await get_pool_status()
        logger.info(f"Pool size: {status.get('size', 'N/A')}")
    """
    if _engine is None:
        return {"status": "not_initialized"}

    pool: Pool = _engine.pool

    # NullPool doesn't have these attributes
    if isinstance(pool, NullPool):
        return {
            "type": "NullPool",
            "note": "Using Supavisor connection pooling, SQLAlchemy pool disabled",
        }

    try:
        return {
            "type": pool.__class__.__name__,
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "total_connections": pool.size() + pool.overflow(),
        }
    except AttributeError:
        return {"type": pool.__class__.__name__, "status": "metrics_unavailable"}
