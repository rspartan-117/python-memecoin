# multi_tenant_sandbox_manager.py - WITH REDIS CACHING
# sandbox_manager.py - FIXED VERSION

import asyncio
import logging
import time
import threading
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

from e2b import AsyncSandbox
from e2b.exceptions import (
    SandboxException,
    AuthenticationException,
    RateLimitException,
    TimeoutException,
)

from redis_client import get_redis, close_redis

# Database imports
from db import get_db_session
from db.models import Project, SandboxState
from db.data_access import ProjectRepository


# Custom exceptions for better error handling
class SandboxResourceLimitError(Exception):
    """Raised when sandbox resource limits are exceeded"""
    
    def __init__(
        self,
        message: str,
        user_id: str,
        project_id: str,
        current_count: int,
        max_allowed: int,
        limit_type: str = "user",  # "user" or "total"
    ):
        super().__init__(message)
        self.message = message
        self.user_id = user_id
        self.project_id = project_id
        self.current_count = current_count
        self.max_allowed = max_allowed
        self.limit_type = limit_type

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to structured dict for API responses"""
        return {
            "error": "resource_limit_exceeded",
            "error_type": "sandbox_limit",
            "message": self.message,
            "details": {
                "user_id": self.user_id,
                "project_id": self.project_id,
                "current_sandboxes": self.current_count,
                "max_allowed": self.max_allowed,
                "limit_type": self.limit_type,
            },
        }


@dataclass
class SandboxConfig:
    """
    Configuration for sandbox creation and management.
    
    TIMEOUT MECHANISM EXPLAINED:
    ===========================
    1. activity_timeout_extension: The ACTIVE timeout mechanism
       - On each activity, sandbox E2B timeout is EXTENDED by this value
       - Also sets Redis cache TTL to this value
       - If no activity for this duration → sandbox becomes idle → cleaned up
       
    2. E2B auto_pause: When sandbox times out on E2B side
       - E2B automatically pauses (not kills) the sandbox
       - We can resume it later via long-term cache (30 days)
       
    FLOW:
    - User makes request → sandbox.set_timeout(activity_timeout_extension)
    - No activity for 10 min → cleanup detects idle → pauses sandbox
    - User returns → reconnects from long-term cache → resumes
    """

    template: Optional[str] = "meme-coin-base-v0"
    timeout: int = (
        600  # 600 seconds (10 min) - E2B API call timeout (not sandbox lifetime)
    )
    auto_pause: bool = True
    allow_internet_access: bool = True
    secure: bool = True
    api_key: Optional[str] = None

    # Pool limits
    max_sandboxes_per_user: int = 2
    max_total_sandboxes: int = 100

    # IDLE TIMEOUT: Primary mechanism for cleanup (10 minutes)
    # If no activity for this duration, sandbox is paused and cleaned from memory
    activity_timeout_extension: int = (
        600  # 600 seconds (10 min) - idle timeout before cleanup
    )

    # Long-term cache settings (database-integrated approach)
    longterm_cache_ttl: int = (
        2592000  # 2592000 seconds (30 days) - TTL for long-term cache in Redis
    )

    # Lifecycle settings
    sandbox_lifecycle_days: int = (
        30  # 30 days - max lifetime for sandboxes based on created_at
    )

    # Retry configuration
    max_retries: int = 2
    retry_delay: float = 1.0

    # Redis caching
    enable_redis: bool = True


@dataclass
class SandboxInfo:
    """
    Information about a sandbox instance.
    
    BILLING/USAGE TRACKING (Monitoring Only):
    - Tracks session time for logging and debugging
    - Actual billing/credit deduction handled by NestJS backend via E2B webhooks
    - These fields provide visibility into sandbox usage patterns
    """

    sandbox: AsyncSandbox
    sandbox_id: str
    user_id: str
    project_id: str
    created_at: float
    last_activity: float
    request_count: int = 0
    paused_at: Optional[float] = None  # Timestamp when paused, None if active
    
    # Usage tracking (for monitoring/logging only - NestJS handles billing)
    session_start_time: Optional[float] = None  # When current active session started
    total_active_seconds: float = 0.0  # Cumulative active time (for logging)

    def is_idle(self, timeout: int) -> bool:
        """Check if sandbox has been idle too long"""
        return (time.time() - self.last_activity) > timeout

    def is_expired(self, max_age: int) -> bool:
        """Check if sandbox has exceeded max age"""
        return (time.time() - self.created_at) > max_age

    def is_paused(self) -> bool:
        """Check if sandbox is paused"""
        return self.paused_at is not None
    
    def get_idle_seconds(self) -> float:
        """Get how long sandbox has been idle"""
        return time.time() - self.last_activity
    
    def get_current_session_seconds(self) -> float:
        """Get current active session duration (for monitoring/logging)"""
        if self.session_start_time is None:
            return 0.0
        if self.paused_at is not None:
            # Session ended at pause time
            return self.paused_at - self.session_start_time
        return time.time() - self.session_start_time
    
    def get_total_billable_seconds(self) -> float:
        """Get total active time (for monitoring/logging - NestJS handles actual billing)"""
        current_session = self.get_current_session_seconds()
        return self.total_active_seconds + current_session
    
    def start_session(self):
        """Start a new active session (for monitoring/logging)"""
        self.session_start_time = time.time()
        self.paused_at = None
    
    def end_session(self):
        """End current session and accumulate time (for monitoring/logging)"""
        if self.session_start_time is not None:
            session_duration = self.get_current_session_seconds()
            self.total_active_seconds += session_duration
            self.paused_at = time.time()
            self.session_start_time = None
            return session_duration
        return 0.0
    
    def get_state_info(self) -> Dict[str, Any]:
        """
        Get sandbox state info for frontend display.
        
        Returns dict with:
        - state: 'running' | 'idle' | 'paused'
        - sandbox_id: str
        - idle_seconds: float
        - total_active_seconds: float (for monitoring - NestJS handles billing)
        - last_activity: ISO timestamp
        - created_at: ISO timestamp
        """
        now = time.time()
        idle_seconds = self.get_idle_seconds()
        
        # Determine state
        if self.paused_at is not None:
            state = "paused"
        elif idle_seconds > 300:  # 5 min = considered idle (but not paused yet)
            state = "idle"
        else:
            state = "running"
        
        return {
            "state": state,
            "sandbox_id": self.sandbox_id,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "idle_seconds": round(idle_seconds, 1),
            "total_active_seconds": round(self.get_total_billable_seconds(), 1),
            "current_session_seconds": round(self.get_current_session_seconds(), 1),
            "request_count": self.request_count,
            "last_activity": datetime.fromtimestamp(self.last_activity).isoformat(),
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "paused_at": datetime.fromtimestamp(self.paused_at).isoformat() if self.paused_at else None,
        }

    async def update_activity(
        self, timeout_seconds: int, logger, redis_update_callback=None
    ):
        """Update last activity timestamp, extend E2B timeout, and update Redis TTL"""
        now = time.time()
        self.last_activity = now
        self.request_count += 1
        
        # Start session if not already started (for billing)
        if self.session_start_time is None:
            self.session_start_time = now
            logger.debug(f"[{self.user_id}/{self.project_id}] Started new billing session")
        
        # Clear paused state when activity updates (sandbox is active)
        if self.paused_at is not None:
            self.paused_at = None

        # Extend E2B sandbox timeout dynamically
        try:
            await self.sandbox.set_timeout(timeout_seconds)
            logger.debug(
                f"[{self.user_id}/{self.project_id}] Extended E2B timeout to {timeout_seconds}s from now"
            )
        except Exception as e:
            logger.warning(
                f"[{self.user_id}/{self.project_id}] Failed to extend E2B timeout: {e}"
            )

        # Update Redis cache TTL to match extended timeout
        if redis_update_callback:
            try:
                await redis_update_callback(
                    self.user_id, self.project_id, self.sandbox_id, timeout_seconds
                )
            except Exception as e:
                logger.warning(
                    f"[{self.user_id}/{self.project_id}] Failed to update Redis TTL: {e}"
                )


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    )
    return logging.getLogger("MultiTenantSandboxManager")


def mask_api_key(api_key: Optional[str]) -> str:
    """Mask API key for safe logging (shows only first 4 and last 4 chars)"""
    if not api_key:
        return "None"
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}...{api_key[-4:]}"


class MultiTenantSandboxManager:
    """
    Production-grade multi-tenant sandbox manager with Redis caching.

    Features:
    - Redis caching of sandbox IDs (TTL = sandbox uptime)
    - Each (user_id, project_id) gets isolated sandbox
    - Automatic cleanup and resource limits
    - Graceful fallback if Redis unavailable
    """

    _instance: Optional["MultiTenantSandboxManager"] = None
    _instance_lock = threading.Lock()  # Use threading.Lock for __new__ (synchronous)
    _instance_async_lock = asyncio.Lock()  # Use asyncio.Lock for async methods

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:  # Thread-safe singleton initialization
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.logger = setup_logging()

        # Sandbox pool: key = (user_id, project_id), value = SandboxInfo
        self._sandbox_pool: Dict[Tuple[str, str], SandboxInfo] = {}
        self._pool_lock = asyncio.Lock()

        # Per-user sandbox creation locks
        self._user_locks: Dict[Tuple[str, str], asyncio.Lock] = {}
        self._user_locks_lock = asyncio.Lock()

        # Configuration
        self._config: Optional[SandboxConfig] = None

        # Redis client
        self._redis: Optional[Any] = None

        # Background tasks
        self._cleanup_task: Optional[asyncio.Task] = None

        # Statistics (protected by stats_lock for thread-safety)
        self._stats = {
            "total_sandboxes_created": 0,
            "total_requests": 0,
            "active_sandboxes": 0,
            "cleaned_up_sandboxes": 0,
            "rejected_requests": 0,
            "redis_cache_hits": 0,
            "redis_cache_misses": 0,
        }
        self._stats_lock = asyncio.Lock()

        self._initialized = True
        self.logger.info("=" * 80)
        self.logger.info("MultiTenantSandboxManager initialized")
        self.logger.info("Each user+project gets isolated sandbox")
        self.logger.info("Redis caching enabled for persistence")
        self.logger.info("=" * 80)

    async def initialize(
        self, config: Optional[SandboxConfig] = None
    ) -> "MultiTenantSandboxManager":
        """Initialize the manager with configuration"""
        async with self._instance_async_lock:
            if config is None:
                config = SandboxConfig()

            if config.api_key is None:
                config.api_key = os.getenv("E2B_API_KEY")
                if not config.api_key:
                    raise ValueError("E2B_API_KEY not set")

            if config.template is None:
                config.template = os.getenv("E2B_TEMPLATE_ID")

            self._config = config

            # Initialize Redis (SYNC CALL - NO AWAIT!)
            if config.enable_redis:
                try:
                    self._redis = get_redis()  # ← SYNC!
                    if self._redis:
                        self.logger.info("✅ Redis caching enabled")
                    else:
                        self.logger.warning("⚠️ Redis unavailable - caching disabled")
                except Exception as e:
                    self.logger.warning(f"⚠️ Redis init failed: {e} - caching disabled")
                    self._redis = None

            self.logger.info(
                f"Configuration: template={config.template or 'default'}, "
                f"max_per_user={config.max_sandboxes_per_user}, "
                f"max_total={config.max_total_sandboxes}, "
                f"redis_enabled={self._redis is not None}, "
                f"api_key={mask_api_key(config.api_key)}"
            )

            # Start cleanup task
            if self._cleanup_task is None:
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())

            return self

    def _validate_userid_projectid(self, user_id: str, project_id: str):
        """
        Validate user_id and project_id with simple checks.

        Args:
            user_id: User identifier
            project_id: Project identifier

        Raises:
            ValueError: If validation fails
        """
        # Check if inputs are provided
        if not user_id:
            raise ValueError("user_id must be a non-empty string")
        if not project_id:
            raise ValueError("project_id must be a non-empty string")

        # Check types
        if not isinstance(user_id, str):
            raise ValueError("user_id must be a string")
        if not isinstance(project_id, str):
            raise ValueError("project_id must be a string")

    # =========================================================================
    # REDIS CACHE OPERATIONS (ALL SYNC - NO ASYNC!)
    # =========================================================================

    def _is_redis_available(self) -> bool:
        """Check if Redis is available and connected"""
        if not self._redis:
            return False
        try:
            # Ping Redis to verify connection is alive
            self._redis.ping()
            return True
        except Exception:
            return False

    def _get_redis_key(self, user_id: str, project_id: str) -> str:
        """Generate Redis key for user+project"""
        return f"sandbox:{user_id}:{project_id}"

    async def _get_cached_sandbox_id(
        self, user_id: str, project_id: str
    ) -> Optional[str]:
        """Get sandbox ID from Redis cache (async wrapper with single retry)"""
        if not self._is_redis_available():
            return None

        key = self._get_redis_key(user_id, project_id)

        # Try with single retry on failure
        for attempt in range(2):
            try:
                # Run sync Redis call in thread pool to avoid blocking event loop
                sandbox_id = await asyncio.to_thread(self._redis.get, key)

                if sandbox_id:
                    # Thread-safe stats update
                    async with self._stats_lock:
                        self._stats["redis_cache_hits"] += 1
                    self.logger.debug(
                        f"[{user_id}/{project_id}] Redis cache HIT: {sandbox_id}"
                    )
                    return sandbox_id
                else:
                    # Thread-safe stats update
                    async with self._stats_lock:
                        self._stats["redis_cache_misses"] += 1
                    self.logger.debug(f"[{user_id}/{project_id}] Redis cache MISS")
                    return None

            except (ConnectionError, TimeoutError, OSError) as e:
                if attempt == 0:
                    # Retry once
                    await asyncio.sleep(0.1)
                    continue
                else:
                    self.logger.warning(f"Redis get error after retry: {e}")
                    return None
            except Exception as e:
                self.logger.error(f"Unexpected Redis get error: {e}")
                return None

        return None

    async def _cache_sandbox_id(
        self, user_id: str, project_id: str, sandbox_id: str, ttl: int
    ):
        """Cache sandbox ID in Redis with TTL (async wrapper with single retry)"""
        if not self._is_redis_available():
            return

        key = self._get_redis_key(user_id, project_id)

        # Try with single retry on failure
        for attempt in range(2):
            try:
                # Run sync Redis call in thread pool to avoid blocking event loop
                await asyncio.to_thread(self._redis.setex, key, ttl, sandbox_id)
                self.logger.debug(
                    f"[{user_id}/{project_id}] Cached in Redis: {sandbox_id} (TTL={ttl}s)"
                )
                return
            except (ConnectionError, TimeoutError, OSError) as e:
                if attempt == 0:
                    # Retry once
                    await asyncio.sleep(0.1)
                    continue
                else:
                    self.logger.warning(f"Redis set error after retry: {e}")
                    return
            except Exception as e:
                self.logger.error(f"Unexpected Redis set error: {e}")
                return

    async def _remove_cached_sandbox_id(self, user_id: str, project_id: str):
        """Remove sandbox ID from Redis cache (async wrapper with single retry)"""
        if not self._is_redis_available():
            return

        key = self._get_redis_key(user_id, project_id)

        # Try with single retry on failure
        for attempt in range(2):
            try:
                # Run sync Redis call in thread pool to avoid blocking event loop
                await asyncio.to_thread(self._redis.delete, key)
                self.logger.debug(f"[{user_id}/{project_id}] Removed from Redis cache")
                return
            except (ConnectionError, TimeoutError, OSError) as e:
                if attempt == 0:
                    # Retry once
                    await asyncio.sleep(0.1)
                    continue
                else:
                    self.logger.warning(f"Redis delete error after retry: {e}")
                    return
            except Exception as e:
                self.logger.error(f"Unexpected Redis delete error: {e}")
                return

    # =========================================================================
    # LONG-TERM CACHE OPERATIONS (30-day TTL)
    # =========================================================================

    def _get_redis_longterm_key(self, user_id: str, project_id: str) -> str:
        """Generate Redis key for long-term cache (30 days)"""
        return f"sandbox:longterm:{user_id}:{project_id}"

    async def _get_longterm_sandbox_id(
        self, user_id: str, project_id: str
    ) -> Optional[str]:
        """Get sandbox ID from long-term Redis cache (30-day TTL)"""
        if not self._is_redis_available():
            return None

        key = self._get_redis_longterm_key(user_id, project_id)

        try:
            sandbox_id = await asyncio.to_thread(self._redis.get, key)
            if sandbox_id:
                self.logger.debug(
                    f"[{user_id}/{project_id}] Long-term cache HIT: {sandbox_id}"
                )
                return sandbox_id
            else:
                self.logger.debug(f"[{user_id}/{project_id}] Long-term cache MISS")
                return None
        except Exception as e:
            self.logger.warning(f"Long-term cache get error: {e}")
            return None

    async def _cache_longterm_sandbox_id(
        self, user_id: str, project_id: str, sandbox_id: str
    ):
        """Cache sandbox ID in long-term Redis cache (30-day TTL)"""
        if not self._is_redis_available():
            return

        key = self._get_redis_longterm_key(user_id, project_id)
        ttl = (
            self._config.longterm_cache_ttl if self._config else 2592000
        )  # 30 days default

        try:
            await asyncio.to_thread(self._redis.setex, key, ttl, sandbox_id)
            self.logger.info(
                f"[{user_id}/{project_id}] Cached in long-term Redis: {sandbox_id} "
                f"(TTL={ttl}s, ~{ttl//86400} days)"
            )
        except Exception as e:
            self.logger.warning(f"Long-term cache set error: {e}")

    async def _remove_longterm_sandbox_id(self, user_id: str, project_id: str):
        """Remove sandbox ID from long-term Redis cache"""
        if not self._is_redis_available():
            return

        key = self._get_redis_longterm_key(user_id, project_id)

        try:
            await asyncio.to_thread(self._redis.delete, key)
            self.logger.debug(f"[{user_id}/{project_id}] Removed from long-term cache")
        except Exception as e:
            self.logger.warning(f"Long-term cache delete error: {e}")

    # =========================================================================
    # DATABASE INTEGRATION HELPERS
    # =========================================================================

    async def _is_sandbox_killed(self, project: Project) -> bool:
        """
        Check if sandbox is killed based on created_at timestamp.
        E2B beta sandboxes are valid for configured lifecycle days (default 30 days).

        Args:
            project: Project instance from database

        Returns:
            True if sandbox is killed (>lifecycle days old), False otherwise
        """
        if not project.active_sandbox_id:
            return False

        lifecycle_days = self._config.sandbox_lifecycle_days if self._config else 30
        elapsed_days = (datetime.now() - project.created_at).days
        is_killed = elapsed_days > lifecycle_days

        if is_killed:
            self.logger.info(
                f"[{project.user_id}/{project.id}] Sandbox killed: "
                f"{elapsed_days} days old (>{lifecycle_days} days)"
            )

        return is_killed

    async def _get_project_from_db(self, project_id: str) -> Optional[Project]:
        """Get project from database"""
        try:
            async with get_db_session() as session:
                repo = ProjectRepository(session)
                project = await repo.get_project(project_id)
                return project
        except Exception as e:
            self.logger.error(f"Database get_project error: {e}")
            return None

    async def _update_sandbox_state_in_db(
        self, project_id: str, sandbox_id: Optional[str], state: SandboxState
    ):
        """Update sandbox state in database"""
        try:
            async with get_db_session() as session:
                repo = ProjectRepository(session)
                await repo.update_sandbox_state(project_id, sandbox_id, state)
                await session.commit()
                self.logger.debug(
                    f"[{project_id}] Updated DB: sandbox_id={sandbox_id}, state={state.value}"
                )
        except Exception as e:
            self.logger.error(f"Database update_sandbox_state error: {e}")

    # =========================================================================
    # SANDBOX RETRIEVAL WITH REDIS
    # =========================================================================
    async def get_sandbox(
        self,
        user_id: str,
        project_id: str,
        metadata: Optional[Dict[str, str]] = None,
        envs: Optional[Dict[str, str]] = None,
    ) -> AsyncSandbox:
        """Get or create sandbox for specific user and project."""

        if not self._config:
            raise ValueError("Manager not initialized. Call initialize() first.")

        # Validate input
        self._validate_userid_projectid(user_id, project_id)

        key = (user_id, project_id)
        async with self._stats_lock:
            self._stats["total_requests"] += 1

        self.logger.info(f"[{user_id}/{project_id}] Sandbox request")

        user_lock = await self._get_user_lock(user_id, project_id)

        async with user_lock:
            # Step 1: Check memory pool
            if key in self._sandbox_pool:
                sandbox_info = self._sandbox_pool[key]

                # Smart health check: Only verify if sandbox has been idle
                idle_seconds = time.time() - sandbox_info.last_activity

                # Skip health check if recently used (< 30s)
                if idle_seconds < 30:
                    await sandbox_info.update_activity(
                        self._config.activity_timeout_extension,
                        self.logger,
                        self._cache_sandbox_id,
                    )
                    self.logger.info(
                        f"[{user_id}/{project_id}] Memory pool HIT (fresh): "
                        f"{sandbox_info.sandbox_id}"
                    )
                    return sandbox_info.sandbox

                # Health check for idle sandboxes only
                try:
                    await self._verify_sandbox_health(sandbox_info.sandbox)
                    await sandbox_info.update_activity(
                        self._config.activity_timeout_extension,
                        self.logger,
                        self._cache_sandbox_id,
                    )
                    self.logger.info(
                        f"[{user_id}/{project_id}] Memory pool HIT (verified): "
                        f"{sandbox_info.sandbox_id}"
                    )
                    return sandbox_info.sandbox
                except (TimeoutError, ConnectionError, SandboxException) as e:
                    self.logger.warning(
                        f"[{user_id}/{project_id}] Health check failed: {e}"
                    )
                    await self._remove_sandbox(key)
                except Exception as e:
                    self.logger.error(
                        f"[{user_id}/{project_id}] Unexpected health check error: {e}"
                    )
                    await self._remove_sandbox(key)

            # Step 2: Check L2 General Cache (Redis - 30 min TTL)
            # Acts as safety lock if L1 cache misses
            cached_sandbox_id = await self._get_cached_sandbox_id(user_id, project_id)

            if cached_sandbox_id:
                try:
                    # Reconnect will automatically resume paused sandboxes (both manual and auto-paused)
                    # AsyncSandbox.connect() handles both cases transparently
                    sandbox = await self._reconnect_to_sandbox(
                        cached_sandbox_id, user_id, project_id
                    )

                    self.logger.info(
                        f"[{user_id}/{project_id}] Reconnected to cached sandbox"
                    )

                    # Update database state to RUNNING
                    try:
                        await self._update_sandbox_state_in_db(
                            project_id, cached_sandbox_id, SandboxState.RUNNING
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"[{user_id}/{project_id}] Failed to update DB state to RUNNING: {e}. "
                            f"Continuing with cached sandbox."
                        )

                    # Use unified update_activity() for complete state management
                    # This handles: timeout extension, Redis TTL, timestamp, counter, paused state
                    key = (user_id, project_id)
                    if key in self._sandbox_pool:
                        sandbox_info = self._sandbox_pool[key]
                        await sandbox_info.update_activity(
                            self._config.activity_timeout_extension,
                            self.logger,
                            self._cache_sandbox_id,
                        )

                    return sandbox
                except (
                    TimeoutError,
                    ConnectionError,
                    SandboxException,
                    AuthenticationException,
                ) as e:
                    # Reconnect failed: Remove from cache, fall through to Step 3
                    self.logger.warning(
                        f"[{user_id}/{project_id}] Reconnect failed for {cached_sandbox_id}: {e}. "
                        f"Proceeding to long-term cache check."
                    )
                    await self._remove_cached_sandbox_id(user_id, project_id)
                    # Fall through to Step 3
                except Exception as e:
                    # Unexpected error: Remove from cache, fall through to Step 3
                    self.logger.error(
                        f"[{user_id}/{project_id}] Unexpected reconnect error for {cached_sandbox_id}: {e}. "
                        f"Proceeding to long-term cache check."
                    )
                    await self._remove_cached_sandbox_id(user_id, project_id)
                    # Fall through to Step 3

            # Step 3: Check Long-Term Cache (Redis - 30 days TTL)
            longterm_id = await self._get_longterm_sandbox_id(user_id, project_id)
            if longterm_id:
                self.logger.info(
                    f"[{user_id}/{project_id}] Long-term cache HIT: {longterm_id}"
                )
                # Try to reconnect - let E2B tell us if it exists
                try:
                    sandbox = await self._reconnect_to_sandbox(
                        longterm_id, user_id, project_id
                    )
                    self.logger.info(
                        f"[{user_id}/{project_id}] Reconnected from long-term cache"
                    )
                    # Success: Update DB and general cache
                    try:
                        await self._update_sandbox_state_in_db(
                            project_id, longterm_id, SandboxState.RUNNING
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"[{user_id}/{project_id}] Failed to update DB state to RUNNING: {e}. "
                            f"Continuing with reconnected sandbox."
                        )

                    # Use unified update_activity() for complete state management
                    # This handles: timeout extension, Redis TTL, timestamp, counter, paused state
                    key = (user_id, project_id)
                    if key in self._sandbox_pool:
                        sandbox_info = self._sandbox_pool[key]
                        await sandbox_info.update_activity(
                            self._config.activity_timeout_extension,
                            self.logger,
                            self._cache_sandbox_id,
                        )

                    return sandbox
                except Exception as e:
                    # E2B says sandbox doesn't exist (deleted, expired, or error)
                    self.logger.warning(
                        f"[{user_id}/{project_id}] Reconnect to long-term cache failed: {e}. "
                        f"Sandbox may be expired or deleted. Creating new sandbox."
                    )
                    # Remove stale long-term cache
                    await self._remove_longterm_sandbox_id(user_id, project_id)

                    # Check if project exists in DB to determine restoration
                    project = await self._get_project_from_db(project_id)
                    restore_session = project is not None

                    await self._enforce_resource_limits(user_id, project_id)
                    sandbox = await self._create_sandbox_for_user(
                        user_id,
                        project_id,
                        metadata,
                        envs,
                        restore_session=restore_session,
                    )
                    return sandbox

            # Step 4: Check Database (ONLY if no long-term cache found)
            # Database is SECONDARY source - fallback when cache missed
            project = await self._get_project_from_db(project_id)

            if project and project.active_sandbox_id:
                # Sandbox ID present in DB
                # Check if killed (>30 days from created_at)
                is_killed = await self._is_sandbox_killed(project)

                if is_killed:
                    # Sandbox expired: Mark as KILLED, create new with restoration
                    self.logger.info(
                        f"[{user_id}/{project_id}] Sandbox in DB is killed (>30 days). "
                        f"Creating new with restoration."
                    )
                    try:
                        await self._update_sandbox_state_in_db(
                            project_id, None, SandboxState.KILLED
                        )
                        await self._remove_longterm_sandbox_id(user_id, project_id)
                    except Exception as e:
                        self.logger.warning(
                            f"[{user_id}/{project_id}] Failed to update DB state to KILLED: {e}. "
                            f"Keeping long-term cache for recovery. Continuing with sandbox creation."
                        )
                    # Create new sandbox + call restoration route
                    await self._enforce_resource_limits(user_id, project_id)
                    sandbox = await self._create_sandbox_for_user(
                        user_id, project_id, metadata, envs, restore_session=True
                    )
                    return sandbox
                else:
                    # Not expired: Try to reconnect
                    try:
                        sandbox = await self._reconnect_to_sandbox(
                            project.active_sandbox_id, user_id, project_id
                        )
                        # Success: Update DB and caches
                        try:
                            await self._update_sandbox_state_in_db(
                                project_id,
                                project.active_sandbox_id,
                                SandboxState.RUNNING,
                            )
                        except Exception as e:
                            self.logger.warning(
                                f"[{user_id}/{project_id}] Failed to update DB state to RUNNING: {e}. "
                                f"Continuing with reconnected sandbox."
                            )

                        # Use unified update_activity() for complete state management
                        # This handles: timeout extension, Redis TTL, timestamp, counter, paused state
                        key = (user_id, project_id)
                        if key in self._sandbox_pool:
                            sandbox_info = self._sandbox_pool[key]
                            await sandbox_info.update_activity(
                                self._config.activity_timeout_extension,
                                self.logger,
                                self._cache_sandbox_id,
                            )

                        return sandbox
                    except Exception as e:
                        # Reconnect failed: Create new with restoration
                        self.logger.warning(
                            f"[{user_id}/{project_id}] Reconnect to DB sandbox failed: {e}. "
                            f"Creating new with restoration."
                        )
                        await self._enforce_resource_limits(user_id, project_id)
                        sandbox = await self._create_sandbox_for_user(
                            user_id, project_id, metadata, envs, restore_session=True
                        )
                        return sandbox
            else:
                # No sandbox_id in DB: Completely new session
                # Indicators:
                # - No long-term cache (checked in Step 3)
                # - No sandbox_id in DB (current check)
                # Create clean new sandbox (no restoration)
                self.logger.info(
                    f"[{user_id}/{project_id}] Completely new session detected "
                    f"(no long-term cache, no sandbox_id in DB). Creating clean sandbox."
                )
                await self._enforce_resource_limits(user_id, project_id)
                sandbox = await self._create_sandbox_for_user(
                    user_id, project_id, metadata, envs, restore_session=False
                )
                return sandbox

    async def _reconnect_to_sandbox(
        self, sandbox_id: str, user_id: str, project_id: str
    ) -> AsyncSandbox:
        """
        Reconnect to an existing sandbox using the public AsyncSandbox.connect() API.
        This method automatically resumes paused sandboxes and is the recommended approach.
        """
        key = (user_id, project_id)

        self.logger.info(f"[{user_id}/{project_id}] Reconnecting: {sandbox_id}")

        try:
            # Use public API to connect to existing sandbox
            # This automatically resumes paused sandboxes and handles connection setup
            sandbox = await asyncio.wait_for(
                AsyncSandbox.connect(
                    sandbox_id,
                    api_key=self._config.api_key,
                    timeout=self._config.timeout,
                ),
                timeout=5.0,
            )

            # Verify it's alive
            try:
                await asyncio.wait_for(
                    self._verify_sandbox_health(sandbox), timeout=5.0
                )
            except asyncio.TimeoutError:
                raise Exception("Sandbox not responding")

            # Check if this was a paused sandbox (preserve created_at if reconnecting)
            # For reconnected sandboxes, we don't know the original created_at,
            # so we use current time but this is okay since cleanup uses Redis TTL
            sandbox_info = SandboxInfo(
                sandbox=sandbox,
                sandbox_id=sandbox_id,
                user_id=user_id,
                project_id=project_id,
                created_at=time.time(),  # Reset on reconnect (cleanup uses Redis TTL anyway)
                last_activity=time.time(),
                paused_at=None,  # Clear paused state on reconnect
            )

            async with self._pool_lock:
                self._sandbox_pool[key] = sandbox_info
                async with self._stats_lock:
                    self._stats["active_sandboxes"] = len(self._sandbox_pool)

            self.logger.info(f"[{user_id}/{project_id}] Reconnected using public API")


            return sandbox

        except (
            TimeoutError,
            ConnectionError,
            SandboxException,
            AuthenticationException,
        ) as e:
            self.logger.warning(f"[{user_id}/{project_id}] Reconnect failed: {e}")
            raise
        except Exception as e:
            self.logger.error(
                f"[{user_id}/{project_id}] Unexpected reconnect error: {e}"
            )
            raise

    async def _get_user_lock(self, user_id: str, project_id: str) -> asyncio.Lock:
        """Get or create lock for specific user+project"""
        key = (user_id, project_id)
        async with self._user_locks_lock:
            if key not in self._user_locks:
                self._user_locks[key] = asyncio.Lock()
            return self._user_locks[key]

    async def _cleanup_user_locks(self):
        """Remove locks for users with no active sandboxes (prevents memory leak)"""
        async with self._user_locks_lock:
            active_keys = set(self._sandbox_pool.keys())
            keys_to_remove = [
                key for key in self._user_locks.keys() if key not in active_keys
            ]
            for key in keys_to_remove:
                del self._user_locks[key]
            if keys_to_remove:
                self.logger.debug(f"Cleaned up {len(keys_to_remove)} unused user locks")

    async def _enforce_resource_limits(self, user_id: str, project_id: str):
        """
        Enforce resource limits before creating a new sandbox.
        
        This method is called BEFORE creating any new sandbox to ensure:
        1. System-wide capacity limits are respected
        2. Per-user fairness limits are enforced
        
        FLOW:
        ═════
        1. PROACTIVE CLEANUP (On-Demand)
           - First, cleanup any idle sandboxes (>10 min inactive)
           - This frees up slots that might be blocking new requests
           - Prevents false rejections when slots are available but idle
        
        2. SYSTEM-WIDE LIMIT CHECK
           - Check total sandboxes across ALL users
           - Default: max 100 sandboxes total
           - Protects server resources and E2B costs
        
        3. PER-USER LIMIT CHECK  
           - Check sandboxes for THIS specific user
           - Default: max 2 sandboxes per user
           - Ensures fair resource sharing among users
        
        WHY ON-DEMAND CLEANUP FIRST?
        ════════════════════════════
        Before this change, cleanup only ran every 30 seconds (background timer).
        This caused false rejections:
        
        OLD FLOW (Problem):
        ┌─────────────────────────────────────────────────────────────┐
        │ Time 0s:  User has 2 idle sandboxes (inactive 11 min)      │
        │ Time 1s:  User requests 3rd sandbox                         │
        │           → Check limits: 2/2 = FULL                        │
        │           → ERROR: "Max sandboxes reached"                  │
        │ Time 30s: Background cleanup runs, removes idle sandboxes   │
        │           → Now 0/2 sandboxes (but user already got error!) │
        └─────────────────────────────────────────────────────────────┘
        
        NEW FLOW (Fixed):
        ┌─────────────────────────────────────────────────────────────┐
        │ Time 0s:  User has 2 idle sandboxes (inactive 11 min)      │
        │ Time 1s:  User requests 3rd sandbox                         │
        │           → _cleanup_idle_sandboxes() runs FIRST            │
        │           → 2 idle sandboxes removed immediately            │
        │           → Check limits: 0/2 = OK                          │
        │           → New sandbox created successfully                │
        └─────────────────────────────────────────────────────────────┘
        
        ERROR RESPONSE STRUCTURE:
        ═════════════════════════
        When limits are exceeded, raises SandboxResourceLimitError with:
        - message: User-friendly explanation
        - user_id: For tracking/debugging
        - project_id: Which project was requesting
        - current_count: How many sandboxes currently exist
        - max_allowed: The configured limit
        - limit_type: "total" or "user" (which limit was hit)
        
        This structured error allows the API to return HTTP 429 with:
        {
            "error": "resource_limit_exceeded",
            "error_type": "sandbox_limit",
            "message": "You have reached maximum...",
            "details": { ... }
        }
        
        Args:
            user_id: The user requesting a new sandbox
            project_id: The project for which sandbox is requested
            
        Raises:
            SandboxResourceLimitError: If any limit is exceeded
        """
        
        # =====================================================================
        # STEP 1: PROACTIVE CLEANUP - Free up idle sandboxes first
        # =====================================================================
        # This is the KEY improvement - cleanup BEFORE checking limits
        # Removes sandboxes idle for > activity_timeout_extension (10 min default)
        await self._cleanup_idle_sandboxes()
        
        # =====================================================================
        # STEP 2: CHECK SYSTEM-WIDE LIMIT
        # =====================================================================
        # Protects against resource exhaustion across all users
        # Default: max_total_sandboxes = 100
        total_sandboxes = len(self._sandbox_pool)
        if total_sandboxes >= self._config.max_total_sandboxes:
            # Track rejection for monitoring
            async with self._stats_lock:
                self._stats["rejected_requests"] += 1
            
            # Raise structured error with all context for API response
            raise SandboxResourceLimitError(
                message=f"System capacity reached. Maximum {self._config.max_total_sandboxes} sandboxes allowed across all users. Please try again later.",
                user_id=user_id,
                project_id=project_id,
                current_count=total_sandboxes,
                max_allowed=self._config.max_total_sandboxes,
                limit_type="total",  # Indicates system-wide limit hit
            )

        # =====================================================================
        # STEP 3: CHECK PER-USER LIMIT
        # =====================================================================
        # Ensures fair sharing - one user can't monopolize all sandboxes
        # Default: max_sandboxes_per_user = 2
        # Key format: (user_id, project_id)
        user_sandboxes = [key for key in self._sandbox_pool.keys() if key[0] == user_id]
        user_sandbox_count = len(user_sandboxes)

        if user_sandbox_count >= self._config.max_sandboxes_per_user:
            # Track rejection for monitoring
            async with self._stats_lock:
                self._stats["rejected_requests"] += 1
            
            # Get list of active project IDs for debugging and user feedback
            # Helps user know which projects to close
            active_projects = [key[1] for key in user_sandboxes]
            
            # Log warning with context for server-side debugging
            self.logger.warning(
                f"[{user_id}/{project_id}] Resource limit hit. "
                f"Active sandboxes: {user_sandbox_count}/{self._config.max_sandboxes_per_user}. "
                f"Active projects: {active_projects}"
            )
            
            # Raise structured error with helpful message including active projects
            # Frontend can display this to help user decide which sandbox to close
            raise SandboxResourceLimitError(
                message=(
                    f"You have reached the maximum number of active sandboxes ({self._config.max_sandboxes_per_user}). "
                    f"Please close unused sandboxes or wait for idle sandboxes to auto-cleanup before creating new ones. "
                    f"Active projects: {', '.join(active_projects)}"
                ),
                user_id=user_id,
                project_id=project_id,
                current_count=user_sandbox_count,
                max_allowed=self._config.max_sandboxes_per_user,
                limit_type="user",  # Indicates per-user limit hit (not system-wide)
            )
        
        # =====================================================================
        # SUCCESS: Both limits passed - sandbox creation can proceed
        # =====================================================================
        # If we reach here, the user is allowed to create a new sandbox

    async def _create_sandbox_for_user(
        self,
        user_id: str,
        project_id: str,
        metadata: Optional[Dict[str, str]] = None,
        envs: Optional[Dict[str, str]] = None,
        restore_session: bool = False,
    ) -> AsyncSandbox:
        """
        Create new sandbox and update DB and caches.

        Args:
            user_id: User ID
            project_id: Project ID
            metadata: Optional metadata for sandbox
            envs: Optional environment variables
            restore_session: If True, restore project files/state (for existing projects).
                           If False, create clean sandbox (for completely new sessions).

        Returns:
            AsyncSandbox: The created sandbox instance
        """
        key = (user_id, project_id)

        session_type = "with restoration" if restore_session else "clean (new session)"
        self.logger.info(
            f"[{user_id}/{project_id}] Creating NEW sandbox {session_type}..."
        )

        full_metadata = {
            "user_id": user_id,
            "project_id": project_id,
            "created_at": datetime.now().isoformat(),
            "restore_session": str(restore_session),
            **(metadata or {}),
        }

        for attempt in range(1, self._config.max_retries + 1):
            try:
                sandbox = await AsyncSandbox.beta_create(
                    template=self._config.template,
                    timeout=self._config.timeout,
                    allow_internet_access=self._config.allow_internet_access,
                    metadata=full_metadata,
                    envs=envs or {},
                    secure=self._config.secure,
                    api_key=self._config.api_key,
                    auto_pause=True,
                )

                # Set working timeout to activity_timeout_extension immediately
                try:
                    await sandbox.set_timeout(self._config.activity_timeout_extension)
                    self.logger.debug(
                        f"[{user_id}/{project_id}] Set initial E2B timeout to {self._config.activity_timeout_extension}s"
                    )
                except Exception as e:
                    self.logger.warning(
                        f"[{user_id}/{project_id}] Failed to set initial E2B timeout: {e}"
                    )

                # Store in memory pool with billing session started
                now = time.time()
                sandbox_info = SandboxInfo(
                    sandbox=sandbox,
                    sandbox_id=sandbox.sandbox_id,
                    user_id=user_id,
                    project_id=project_id,
                    created_at=now,
                    last_activity=now,
                    session_start_time=now,  # Start billing session
                    total_active_seconds=0.0,
                )

                async with self._pool_lock:
                    self._sandbox_pool[key] = sandbox_info
                    async with self._stats_lock:
                        self._stats["total_sandboxes_created"] += 1
                        self._stats["active_sandboxes"] = len(self._sandbox_pool)

                # Update database
                try:
                    await self._update_sandbox_state_in_db(
                        project_id, sandbox.sandbox_id, SandboxState.RUNNING
                    )
                except Exception as e:
                    self.logger.warning(
                        f"[{user_id}/{project_id}] Failed to update DB with new sandbox: {e}. "
                        f"Sandbox created but DB state may be stale."
                    )

                # Update general cache with activity timeout TTL
                redis_ttl = self._config.activity_timeout_extension
                await self._cache_sandbox_id(
                    user_id,
                    project_id,
                    sandbox.sandbox_id,
                    ttl=redis_ttl,
                )

                # Update long-term cache (30 days TTL)
                # Always update long-term cache for new sandboxes
                # This ensures recovery even if previous cache expired
                await self._cache_longterm_sandbox_id(
                    user_id, project_id, sandbox.sandbox_id
                )

                if not restore_session:
                    self.logger.info(
                        f"[{user_id}/{project_id}] Set long-term cache (new session, first sandbox)"
                    )
                else:
                    self.logger.info(
                        f"[{user_id}/{project_id}] Updated long-term cache (restored session, new sandbox)"
                    )

                # If restoration needed, call restoration route
                if restore_session:
                    await self._restore_project_session(sandbox, user_id, project_id)


                self.logger.info("=" * 80)
                self.logger.info(f"[{user_id}/{project_id}] Sandbox created!")
                self.logger.info(f"   Sandbox ID: {sandbox.sandbox_id}")
                self.logger.info(f"   Session Type: {session_type}")
                self.logger.info(f"   Redis TTL: {redis_ttl}s")
                self.logger.info(f"   Active: {len(self._sandbox_pool)}")
                self.logger.info("=" * 80)

                return sandbox

            except (
                SandboxException,
                AuthenticationException,
                RateLimitException,
                TimeoutException,
            ) as e:
                if attempt < self._config.max_retries:
                    delay = self._config.retry_delay * (2 ** (attempt - 1))
                    self.logger.warning(
                        f"[{user_id}/{project_id}] Attempt {attempt} failed: {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
            except Exception as e:
                self.logger.error(
                    f"[{user_id}/{project_id}] Unexpected error creating sandbox: {e}"
                )
                raise

        raise RuntimeError("Failed to create sandbox after retries")

    async def _restore_project_session(
        self, sandbox: AsyncSandbox, user_id: str, project_id: str
    ):
        """
        Restore project files and state to a new sandbox.

        This is called when creating a new sandbox for an existing project
        (e.g., after sandbox expiration or reconnection failure).

        Args:
            sandbox: The newly created sandbox
            user_id: User ID
            project_id: Project ID
        """
        try:
            self.logger.info(
                f"[{user_id}/{project_id}] Starting session restoration..."
            )

            # TODO: Implement session restoration logic
            # This should:
            # 1. Fetch project files from database
            # 2. Write files to sandbox
            # 3. Restore any project state/context
            # 4. Restore environment variables

            # For now, just log that restoration would happen here
            self.logger.info(
                f"[{user_id}/{project_id}] Session restoration placeholder "
                f"(implement file/state restoration here)"
            )

        except Exception as e:
            # Log error but don't fail sandbox creation
            self.logger.warning(
                f"[{user_id}/{project_id}] Session restoration failed: {e}. "
                f"Sandbox created but files not restored."
            )

    async def _verify_sandbox_health(self, sandbox: AsyncSandbox):
        """Quick health check"""
        try:
            await asyncio.wait_for(sandbox.files.list("."), timeout=3.0)
        except (TimeoutError, ConnectionError, SandboxException) as e:
            raise Exception(f"Health check failed: {e}")
        except Exception as e:
            raise Exception(f"Unexpected health check error: {e}")


    async def pause_sandbox(
        self, user_id: str, project_id: str, timeout: Optional[int] = None
    ) -> str:
        """
        Manually pause a sandbox and remove it from active caches.

        Note: This is a convenience API. E2B also auto-pauses sandboxes after timeout
        (when auto_pause=True in config). This method is for users who want to pause
        manually to save credits.

        This method:
        1. Pauses the sandbox via E2B (saves state, stops billing)
        2. Removes from L1 memory pool (saves memory)
        3. Removes from general cache (30 min TTL)
        4. Keeps in long-term cache (30 day TTL) for recovery
        5. Updates database state to PAUSED

        Recovery:
        - Sandbox can be resumed via long-term cache (30 days)
        - Database maintains state for persistence beyond cache expiry

        Args:
            user_id: User ID
            project_id: Project ID
            timeout: Optional timeout to set before pausing

        Returns:
            str: Sandbox ID that was paused

        Raises:
            ValueError: If sandbox not found
            HTTPException: If pause fails
        """
        self._validate_userid_projectid(user_id, project_id)
        key = (user_id, project_id)

        # Get sandbox from pool or Redis
        sandbox = None
        sandbox_id = None

        # Try to get from pool first
        async with self._pool_lock:
            if key in self._sandbox_pool:
                sandbox_info = self._sandbox_pool[key]
                sandbox = sandbox_info.sandbox
                sandbox_id = sandbox_info.sandbox_id
                # Mark as paused
                sandbox_info.paused_at = time.time()

        # If not in pool, try to get from Redis and connect
        if not sandbox:
            cached_sandbox_id = await self._get_cached_sandbox_id(user_id, project_id)
            if not cached_sandbox_id:
                raise ValueError(
                    f"Sandbox not found for user {user_id}, project {project_id}"
                )
            sandbox_id = cached_sandbox_id
            try:
                sandbox = await AsyncSandbox.connect(
                    sandbox_id, api_key=self._config.api_key
                )
            except Exception as e:
                raise ValueError(f"Failed to connect to sandbox {sandbox_id}: {e}")

        # Update timeout if provided
        if timeout is not None and timeout > 0:
            try:
                await sandbox.set_timeout(timeout)
                self.logger.info(
                    f"[{user_id}/{project_id}] Updated timeout to {timeout}s before pause"
                )
            except Exception as e:
                self.logger.warning(f"Failed to update timeout: {e}")

        # Pause the sandbox
        try:
            await sandbox.beta_pause()
            self.logger.info(
                f"[{user_id}/{project_id}] Sandbox {sandbox_id} paused successfully"
            )
        except AttributeError:
            # Fallback
            if hasattr(sandbox, "pause"):
                await sandbox.pause()
            else:
                raise ValueError("Pause functionality not available")
        except Exception as e:
            raise ValueError(f"Failed to pause sandbox: {e}")

        # Remove from L1 pool (save memory)
        async with self._pool_lock:
            if key in self._sandbox_pool:
                del self._sandbox_pool[key]
                async with self._stats_lock:
                    self._stats["active_sandboxes"] = len(self._sandbox_pool)

        # Remove from general cache
        # Long-term cache (30 days) will still have it for recovery
        await self._remove_cached_sandbox_id(user_id, project_id)

        # Update database state to PAUSED
        try:
            await self._update_sandbox_state_in_db(
                project_id, sandbox_id, SandboxState.PAUSED
            )
            self.logger.info(
                f"[{user_id}/{project_id}] Sandbox paused. "
                f"Removed from active caches, recoverable via long-term cache (30 days) or database."
            )
        except Exception as e:
            self.logger.warning(
                f"[{user_id}/{project_id}] Failed to update database state to PAUSED: {e}"
            )
            self.logger.info(
                f"[{user_id}/{project_id}] Sandbox paused. "
                f"Removed from active caches, recoverable via long-term cache (30 days)."
            )

        return sandbox_id

    async def reconnect_and_register_sandbox(
        self, sandbox_id: str, user_id: str, project_id: str
    ) -> AsyncSandbox:
        """
        Public method to reconnect to a sandbox and register it in the pool.

        This is used by API routes (like resume) to ensure the sandbox is properly
        tracked in the manager's pool after reconnection. Automatically resumes
        paused sandboxes (both manually paused and E2B auto-paused).

        Note: AsyncSandbox.connect() automatically resumes paused sandboxes,
        whether they were manually paused or auto-paused by E2B after timeout.

        Args:
            sandbox_id: The sandbox ID to reconnect to
            user_id: User ID for tracking
            project_id: Project ID for tracking

        Returns:
            AsyncSandbox: The reconnected sandbox instance
        """
        # Validate input
        self._validate_userid_projectid(user_id, project_id)
        sandbox = await self._reconnect_to_sandbox(sandbox_id, user_id, project_id)

        # Update database state to RUNNING
        try:
            await self._update_sandbox_state_in_db(
                project_id, sandbox_id, SandboxState.RUNNING
            )
        except Exception as e:
            self.logger.warning(
                f"[{user_id}/{project_id}] Failed to update DB state to RUNNING: {e}. "
                f"Continuing with reconnected sandbox."
            )

        # Use unified update_activity() for complete state management
        # This handles: timeout extension, Redis TTL, timestamp, counter, paused state
        # This handles both manually paused and E2B auto-paused sandboxes
        key = (user_id, project_id)
        if key in self._sandbox_pool:
            sandbox_info = self._sandbox_pool[key]
            await sandbox_info.update_activity(
                self._config.activity_timeout_extension,
                self.logger,
                self._cache_sandbox_id,
            )

        return sandbox

    async def close_sandbox(self, user_id: str, project_id: str):
        """Close sandbox and remove from Redis"""
        # Validate input
        self._validate_userid_projectid(user_id, project_id)
        key = (user_id, project_id)
        await self._remove_sandbox(key)
        await self._remove_cached_sandbox_id(user_id, project_id)

    async def _remove_sandbox(self, key: Tuple[str, str]):
        """
        Remove and close sandbox from pool.
        
        Note: Billing/credit tracking is handled by NestJS backend via E2B webhooks.
        We log usage info here for monitoring/debugging only.
        """
        async with self._pool_lock:
            if key in self._sandbox_pool:
                sandbox_info = self._sandbox_pool[key]
                
                # End session for logging (NestJS handles actual billing)
                session_seconds = sandbox_info.end_session()
                total_seconds = sandbox_info.total_active_seconds
                
                self.logger.info(
                    f"[{key[0]}/{key[1]}] Session ended: {session_seconds:.1f}s this session, "
                    f"{total_seconds:.1f}s total, {sandbox_info.request_count} requests "
                    f"(billing handled by NestJS)"
                )

                try:
                    await sandbox_info.sandbox.beta_pause()
                    self.logger.info(
                        f"[{key[0]}/{key[1]}] Closed: {sandbox_info.sandbox_id}"
                    )
                except Exception as e:
                    # Handle 409 Conflict: sandbox already paused/killed
                    error_msg = str(e).lower()
                    if "409" in error_msg or "conflict" in error_msg or "already paused" in error_msg:
                        self.logger.info(
                            f"[{key[0]}/{key[1]}] Sandbox already paused/killed: {sandbox_info.sandbox_id}"
                        )
                    else:
                        self.logger.warning(f"Error closing sandbox: {e}")

                del self._sandbox_pool[key]
                async with self._stats_lock:
                    self._stats["active_sandboxes"] = len(self._sandbox_pool)
                    self._stats["cleaned_up_sandboxes"] += 1

        # Remove from Redis cache (async, outside pool_lock to avoid deadlock)
        await self._remove_cached_sandbox_id(key[0], key[1])

        # Cleanup unused user locks to prevent memory leak (outside pool_lock to avoid deadlock)
        # await self._cleanup_user_locks()
        
     # return billing_seconds

    async def _cleanup_idle_sandboxes(self):
        """Cleanup idle sandboxes immediately (used before resource limit checks)"""
        if not self._config:
            return

        keys_to_remove = []

        async with self._pool_lock:
            for key, sandbox_info in self._sandbox_pool.items():
                # Skip manually paused sandboxes in L1 pool
                if sandbox_info.is_paused():
                    continue

                # Check if inactive longer than activity_timeout_extension
                if sandbox_info.is_idle(self._config.activity_timeout_extension):
                    self.logger.info(
                        f"[{key[0]}/{key[1]}] On-demand cleanup: Inactive for >{self._config.activity_timeout_extension}s"
                    )
                    keys_to_remove.append(key)

        # Remove active sandboxes that are idle/expired
        for key in keys_to_remove:
            await self._remove_sandbox(key)

    async def _cleanup_loop(self):
        """
        Background cleanup task.

        Important: E2B auto-pauses sandboxes after timeout (auto_pause=True).
        This means sandboxes in Redis may be auto-paused by E2B, not just manually paused.

        Edge cases handled:
        1. Manually paused sandboxes: Removed from active caches, recovered via long-term cache (30 days) or database
        2. E2B auto-paused sandboxes: Kept in long-term cache for fast reconnection
        3. Expired active sandboxes: Removed from both L1 and Redis
        4. Idle active sandboxes: Removed from both L1 and Redis
        5. Database serves as source of truth for sandbox state recovery
        """
        while True:
            try:
                await asyncio.sleep(30)

                # Use the on-demand cleanup method
                await self._cleanup_idle_sandboxes()

                # Cleanup unused user locks periodically
                await self._cleanup_user_locks()

            except Exception as e:
                self.logger.error(f"Cleanup error: {e}")
                await asyncio.sleep(30)  # Prevent tight error loop

    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics"""
        return {
            **self._stats,
            "active_sandboxes": len(self._sandbox_pool),
            "redis_enabled": self._redis is not None,
            "cache_hit_rate": (
                self._stats["redis_cache_hits"]
                / (self._stats["redis_cache_hits"] + self._stats["redis_cache_misses"])
                if (self._stats["redis_cache_hits"] + self._stats["redis_cache_misses"])
                > 0
                else 0
            ),
        }

    async def get_sandbox_state(
        self, user_id: str, project_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get sandbox state info for frontend display.
        
        Returns None if sandbox not found in memory pool.
        For paused/cached sandboxes, check database or long-term cache.
        
        Frontend states:
        - 'running': Active and recently used
        - 'idle': Active but not used for >5 min (will auto-cleanup at 10 min)
        - 'paused': Paused (either manually or by cleanup)
        - 'closed': Not in memory (check database for historical state)
        
        Returns:
            Dict with state info or None if not in memory
        """
        key = (user_id, project_id)
        
        async with self._pool_lock:
            if key in self._sandbox_pool:
                sandbox_info = self._sandbox_pool[key]
                return sandbox_info.get_state_info()
        
        # Not in memory - check caches to determine state
        cached_id = await self._get_cached_sandbox_id(user_id, project_id)
        longterm_id = await self._get_longterm_sandbox_id(user_id, project_id)
        
        if cached_id:
            # In general cache but not in memory = paused or recently disconnected
            return {
                "state": "paused",
                "sandbox_id": cached_id,
                "user_id": user_id,
                "project_id": project_id,
                "message": "Sandbox is paused. Will resume on next request.",
            }
        elif longterm_id:
            # Only in long-term cache = paused for a while
            return {
                "state": "paused",
                "sandbox_id": longterm_id,
                "user_id": user_id,
                "project_id": project_id,
                "message": "Sandbox is paused (recoverable for 30 days). Will resume on next request.",
            }
        else:
            # Not found anywhere
            return {
                "state": "closed",
                "sandbox_id": None,
                "user_id": user_id,
                "project_id": project_id,
                "message": "No active sandbox. New sandbox will be created on next request.",
            }

    async def get_user_sandboxes_state(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get state info for all sandboxes belonging to a user.
        Useful for frontend dashboard showing all user's projects.
        
        Returns:
            List of sandbox state dicts
        """
        results = []
        
        async with self._pool_lock:
            for key, sandbox_info in self._sandbox_pool.items():
                if key[0] == user_id:
                    results.append(sandbox_info.get_state_info())
        
        return results

    async def list_paused_sandboxes(
        self, api_key: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List all paused sandboxes using AsyncSandbox.list().

        Args:
            api_key: E2B API key (optional, will use config api_key if not provided)

        Returns:
            List of dictionaries containing paused sandbox information
        """
        if api_key is None:
            if not self._config or not self._config.api_key:
                raise ValueError("E2B_API_KEY not set in config or environment")
            api_key = self._config.api_key

        # Try to import SandboxQuery and SandboxState (may not be available in all SDK versions)
        try:
            from e2b import SandboxQuery, SandboxState
        except ImportError:
            try:
                from e2b_code_interpreter import SandboxQuery, SandboxState
            except ImportError:
                SandboxQuery = None
                SandboxState = None

        try:
            # Try using SandboxQuery and SandboxState if available
            if SandboxQuery is not None and SandboxState is not None:
                # Create query for paused sandboxes
                query = SandboxQuery(state=[SandboxState.PAUSED])

                # Get paginator for paused sandboxes
                paginator = AsyncSandbox.list(query=query, api_key=api_key)

                # Collect all paused sandboxes
                paused_sandboxes = []

                # Get the first page
                items = await paginator.next_items()
                paused_sandboxes.extend(items)

                # Get all remaining pages
                while paginator.has_next:
                    items = await paginator.next_items()
                    paused_sandboxes.extend(items)

                # Convert to list of dictionaries with relevant information
                result = []
                for sandbox in paused_sandboxes:
                    result.append(
                        {
                            "sandbox_id": sandbox.sandbox_id,
                            "state": "paused",
                            "template_id": getattr(sandbox, "template_id", None),
                            "metadata": getattr(sandbox, "metadata", {}),
                        }
                    )

                return result
            else:
                # Fallback if SandboxQuery/SandboxState not available
                # List all sandboxes and filter for paused ones
                paginator = AsyncSandbox.list(api_key=api_key)
                all_sandboxes = []

                items = await paginator.next_items()
                all_sandboxes.extend(items)

                while paginator.has_next:
                    items = await paginator.next_items()
                    all_sandboxes.extend(items)

                # Filter for paused sandboxes
                paused_sandboxes = [
                    s
                    for s in all_sandboxes
                    if getattr(s, "state", None) == "paused"
                    or getattr(s, "status", None) == "paused"
                ]

                result = []
                for sandbox in paused_sandboxes:
                    result.append(
                        {
                            "sandbox_id": sandbox.sandbox_id,
                            "state": "paused",
                            "template_id": getattr(sandbox, "template_id", None),
                            "metadata": getattr(sandbox, "metadata", {}),
                        }
                    )

                return result

        except Exception as e:
            self.logger.error(f"Failed to list paused sandboxes: {e}", exc_info=True)
            raise ValueError(f"Failed to list paused sandboxes: {str(e)}")

    async def shutdown(self):
        """Shutdown manager"""
        self.logger.info("Shutting down...")

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        keys = list(self._sandbox_pool.keys())
        for key in keys:
            await self._remove_sandbox(key)

        # Close Redis (SYNC CALL!)
        close_redis()  # ← NO AWAIT!

        stats = self.get_stats()
        self.logger.info("=" * 80)
        self.logger.info("FINAL STATS:")
        self.logger.info(f"  Total created: {stats['total_sandboxes_created']}")
        self.logger.info(f"  Redis cache hits: {stats['redis_cache_hits']}")
        self.logger.info(f"  Cache hit rate: {stats['cache_hit_rate']:.1%}")
        self.logger.info("=" * 80)


# Global instance
_multi_tenant_manager: Optional[MultiTenantSandboxManager] = None
_manager_lock = asyncio.Lock()


async def get_multi_tenant_manager() -> MultiTenantSandboxManager:
    """Get the global multi-tenant manager"""
    global _multi_tenant_manager

    async with _manager_lock:
        if _multi_tenant_manager is None:
            _multi_tenant_manager = MultiTenantSandboxManager()
            await _multi_tenant_manager.initialize()

        return _multi_tenant_manager


async def get_user_sandbox(user_id: str, project_id: str, **kwargs) -> AsyncSandbox:
    """Convenience function to get sandbox for user+project"""
    # Validation is done in manager.get_sandbox() method
    manager = await get_multi_tenant_manager()
    return await manager.get_sandbox(user_id, project_id, **kwargs)


async def list_paused_sandboxes(api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Convenience function to list all paused sandboxes.
    Uses the global multi-tenant manager instance.

    Args:
        api_key: E2B API key (optional, will use manager config if not provided)

    Returns:
        List of dictionaries containing paused sandbox information
    """
    manager = await get_multi_tenant_manager()
    return await manager.list_paused_sandboxes(api_key=api_key)


async def cleanup_multi_tenant_manager():
    """Cleanup on shutdown"""
    global _multi_tenant_manager
    if _multi_tenant_manager:
        await _multi_tenant_manager.shutdown()
        _multi_tenant_manager = None
