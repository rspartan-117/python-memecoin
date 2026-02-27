# Sandbox Management - Database Integrated Approach

## Overview

This document describes a new approach to sandbox management that integrates with the database (PostgreSQL) to handle the 30-day lifecycle of E2B beta sandboxes. The approach uses the `Project` table as the source of truth and implements a two-layer caching mechanism for optimal performance.

## Key Requirements

1. **E2B Beta Sandbox Lifecycle**: E2B beta sandboxes are valid for 30 days, after which they are automatically deleted
2. **Database as Source of Truth**: Use `Project` table to store sandbox state and track lifecycle
3. **Two-Layer Caching in Redis**: 
   - **General Cache**: `(user_id, project_id)` → `sandbox_id` (30 min TTL) - Acts as L1-like cache in Redis, safety lock if memory L1 misses
   - **Long-term cache**: `(user_id, project_id)` → `sandbox_id` (30-day TTL for standby)
4. **State Synchronization**: Keep database in sync with pause/auto-pause operations
5. **Lifecycle Management**: Use `created_at` from projects table to determine if sandbox is killed (>30 days)

---

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                      │
│                                                                 │
│  ┌──────────────────┐         ┌──────────────────────────┐   │
│  │  API Routes      │────────▶│  MultiTenantSandboxManager│   │
│  │  /api/sandbox/*  │         │  (Enhanced)                │   │
│  └──────────────────┘         └──────────────────────────┘   │
│         │                                │                     │
│         │                                │                     │
│         │                                ▼                     │
│         │                      ┌──────────────────┐           │
│         │                      │   L1 Cache       │           │
│         │                      │   (Memory Pool)  │           │
│         │                      │   Active Sandboxes│           │
│         │                      └──────────────────┘           │
│         │                                │                     │
│         │                                ▼                     │
│         └───────────────────────────────┼─────────────────────┘
│                                         │
│                                         ▼
│                              ┌──────────────────┐
│                              │   L2 Cache       │
│                              │   (Redis)        │
│                              │   Two Layers:    │
│                              │   - General      │
│                              │   - Long-term    │
│                              └──────────────────┘
│                                         │
│                                         ▼
│                              ┌──────────────────┐
│                              │   Database      │
│                              │   (PostgreSQL)   │
│                              │   Project Table  │
│                              │   Source of Truth│
│                              └──────────────────┘
│                                         │
│                                         ▼
│                              ┌──────────────────┐
│                              │   E2B API        │
│                              │   (External)     │
│                              └──────────────────┘
└─────────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### Project Table Fields (Relevant)

```python
class Project(Base):
    id: str                          # Project ID (also used as session_id)
    user_id: str                     # User ID
    active_sandbox_id: Optional[str] # E2B sandbox ID
    sandbox_state: str               # RUNNING, PAUSED, KILLED, NONE
    created_at: datetime             # Project creation time (source of truth)
    last_active: datetime             # Last activity timestamp
    updated_at: datetime             # Last update timestamp
```

### State Management

| State | Description | When Set |
|-------|-------------|----------|
| `NONE` | No sandbox created yet | Initial state |
| `RUNNING` | Sandbox is active | After creation/resume |
| `PAUSED` | Sandbox is paused (manual or auto) | After pause operation |
| `KILLED` | Sandbox expired (>30 days) | Calculated from `created_at` |

---

## Two-Layer Caching Strategy

### Layer 1: General Cache (Active Sandbox)

**Purpose**: Fast retrieval for currently active sandboxes. Acts as L1-like cache in Redis (safety lock if memory L1 cache misses).

**Redis Key**: `sandbox:{user_id}:{project_id}`
**Value**: `sandbox_id`
**TTL**: 30 minutes (1800 seconds)

**When Used**:
- Active sandbox operations
- Fast lookup during request handling
- Safety lock when L1 memory pool misses
- If found: Sandbox is paused or running (not killed) - just connect to it
- Handles both paused and running scenarios automatically

**Lifecycle**:
- Created: When sandbox is created/resumed
- Updated: On activity
- Removed: On pause, cleanup, or expiration

### Layer 2: Long-Term Cache (Standby)

**Purpose**: Maintain sandbox_id for 30-day standby period per project

**Redis Key**: `sandbox:longterm:{user_id}:{project_id}`
**Value**: `sandbox_id`
**TTL**: 30 days (2592000 seconds)

**When Used**:
- Fallback when general cache misses
- After Redis restart
- When checking if sandbox exists for a specific project (before creating new one)
- Session restoration scenarios

**Lifecycle**:
- Created: On first sandbox creation for a project
- Updated: Never (only set once per project)
- Removed: After 30 days or when sandbox is confirmed killed

**Note**: This cache is per `(user_id, project_id)` to support:
- Multiple projects per user
- Project-specific session restoration
- Accurate sandbox tracking per project

---

## Core Logic Flow

### 1. Sandbox Creation Flow

```
┌─────────────────────────────────────────────────────────────┐
│              get_sandbox(user_id, project_id)               │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────┐
        │  STEP 1: Check L1 Memory Pool     │
        │  Key = (user_id, project_id)     │
        └───────────────────────────────────┘
                            │
                ┌───────────┴───────────┐
                │                      │
            FOUND                  NOT FOUND
                │                      │
                ▼                      ▼
    ┌───────────────────┐    ┌──────────────────────┐
    │ Return sandbox    │    │ STEP 2: Check L2     │
    │ (fast path)       │    │ General Cache        │
    └───────────────────┘    │ sandbox:{uid}:{pid} │
                             │ (30 min TTL)        │
                             └──────────────────────┘
                                        │
                                ┌───────┴───────┐
                                │               │
                            FOUND          NOT FOUND
                                │               │
                                ▼               ▼
                    ┌─────────────────┐  ┌──────────────────┐
                    │ Cache present = │  │ STEP 3: Check    │
                    │ Sandbox paused/ │  │ Long-Term Cache  │
                    │ running (not    │  │ sandbox:longterm:│
                    │ killed)         │  │ {uid}:{pid}      │
                    │                 │  └──────────────────┘
                    │ Just connect    │           │
                    │ (handles both   │   ┌───────┴───────┐
                    │ paused/running) │   │               │
                    └─────────────────┘   │           FOUND
                                │         │               │
                                ▼         │               ▼
                    ┌─────────────────┐   │   ┌──────────────────┐
                    │ Connect to      │   │   │ Check DB if      │
                    │ sandbox         │   │   │ killed (>30 days)│
                    └─────────────────┘   │   │ from created_at  │
                                │         │   └──────────────────┘
                    ┌───────────┴──────┐  │           │
                    │                  │  │   ┌───────┴──────┐
                SUCCESS            FAILED│  │   │             │
                    │                  │  │ KILLED    NOT KILLED
                    ▼                  │  │   │             │
            Register in L1/L2    │      │   ▼             ▼
            Update DB            │      │ ┌──────────┐  ┌──────────────┐
            Return sandbox       │      │ │ Create   │  │ Try to       │
                                │      │ │ new +    │  │ connect      │
                                │      │ │ restore  │  └──────────────┘
                                │      │ └──────────┘           │
                                │      │       │      ┌───────┴──────┐
                                │      │       │      │             │
                                │      │       │  SUCCESS       FAILED
                                │      │       │      │             │
                                │      │       │      ▼             ▼
                                │      │       │  Register      Create new
                                │      │       │  in L1/L2      + restore
                                │      │       │  Update DB
                                │      │       │
                                │      └───────┼───────────────────┘
                                │              │
                                └──────────────┼──────────────┐
                                               │              │
                                               ▼              ▼
                                    ┌──────────────────┐  ┌──────────────────┐
                                    │ STEP 4: Check DB│  │ STEP 4: Check DB│
                                    │ Get project     │  │ Get project     │
                                    │ Check sandbox_id│  │ Check sandbox_id│
                                    └──────────────────┘  └──────────────────┘
                                               │              │
                                    ┌───────────┴──────┐  ┌───┴──────┐
                                    │                  │  │         │
                                SANDBOX_ID      NO SANDBOX_ID
                                PRESENT         │         │
                                    │          │         │
                                    ▼          │         │
                            ┌──────────────┐  │         │
                            │ Check if     │  │         │
                            │ killed?      │  │         │
                            └──────────────┘  │         │
                                    │         │         │
                            ┌───────┴──────┐ │         │
                            │             │ │         │
                        KILLED      NOT KILLED│         │
                            │             │ │         │
                            ▼             ▼ │         ▼
                    ┌──────────────┐ ┌──────────┐ ┌──────────────────────┐
                    │ Create new   │ │ Try      │ │ Create NEW sandbox   │
                    │ + restore    │ │ connect  │ │ (Completely new      │
                    │              │ │          │ │  session)            │
                    └──────────────┘ └──────────┘ │ Indicators:          │
                            │             │       │ - No long-term cache │
                            │             │       │ - No sandbox_id in DB│
                            │             │       │ No restoration       │
                            │             │       │ Update DB + Caches   │
                            │             │       └──────────────────────┘
                            └─────────────┴───────┘
                                        │
                                        ▼
                            ┌──────────────────────┐
                            │ Update Database      │
                            │ Update Caches        │
                            │ Register in L1       │
                            └──────────────────────┘
```

**Detailed Steps**:

1. **Check L1 Memory Pool**: Fast path for active sandboxes
   - Key: `(user_id, project_id)`
   - If found: Return immediately (fastest path)

2. **Check L2 General Cache (Redis - 30 min TTL)**: 
   - Key: `sandbox:{user_id}:{project_id}`
   - **Purpose**: Safety lock if L1 cache misses. Acts as L1-like cache in Redis.
   - **If found**: 
     - Sandbox is paused or running (not killed)
     - Handles both paused and running scenarios automatically
     - Try to connect to sandbox
     - If connection succeeds: Register in L1, update DB, return sandbox
     - If connection fails: Proceed to Step 3 (check long-term cache)

3. **Check Long-Term Cache (Redis - 30 days TTL)**:
   - Key: `sandbox:longterm:{user_id}:{project_id}`
   - **If found**: 
     - Sandbox is probably paused or killed
     - Check DB if killed (>30 days from `created_at`)
     - **If killed**: 
       - Mark as KILLED in DB
       - Create new sandbox + call restoration route (project exists, restore files/state)
     - **If not killed**: 
       - Try to connect to sandbox
       - If connection succeeds: Register in L1/L2, update DB, return
       - If connection fails: Create new sandbox + restoration
   - **If not found**: Proceed to Step 4 (check DB)

4. **Check Database**:
   - **Note**: Project is always present (created before sandbox request)
   - Query `Project` table by `project_id`
   - Check if `active_sandbox_id` is present:
     - **If sandbox_id present**:
       - Check `created_at` to determine if >30 days (expired/killed)
       - **If expired/killed**: 
         - Mark as KILLED in DB
         - Create new sandbox + call restoration route (project exists, restore files/state)
       - **If not expired**: 
         - Try to reconnect to `active_sandbox_id`
         - If reconnect succeeds: Register in L1/L2, update DB, return
         - If reconnect fails: Create new sandbox + restoration
     - **If sandbox_id NOT present**:
       - **Indicators for completely new session**:
         - ✅ No long-term cache (checked in Step 3)
         - ✅ No sandbox_id in DB (current check)
       - **Action**: Create clean new sandbox (no restoration)
       - Update DB: Set `active_sandbox_id` and `sandbox_state = RUNNING`
       - Update caches: General cache + Long-term cache (first creation)

5. **Create New Sandbox**:
   - **With Session Restoration** (if project exists with files/state):
     - **When**: Project has `active_sandbox_id` but sandbox is killed/expired or reconnect failed
     - Restore project files, state, and context
     - Use existing project metadata
     - Call restoration route on the new sandbox
   - **Without Restoration** (completely new session):
     - **Indicators**:
       - ✅ No long-term cache
       - ✅ No sandbox_id in DB
     - **Action**: Create clean fresh sandbox
     - No restoration needed (no previous files/state to restore)
     - This is the first sandbox for this project

6. **Update Database**:
   - Set `active_sandbox_id` = new sandbox_id
   - Set `sandbox_state` = RUNNING
   - Update `last_active` = now()

7. **Update Caches**:
   - L1: Register in memory pool
   - General cache: `sandbox:{user_id}:{project_id}` → `sandbox_id` (30 min TTL)
   - Long-term cache: `sandbox:longterm:{user_id}:{project_id}` → `sandbox_id` (30 days TTL, only if first creation for this project)

### 2. Pause Flow (Manual or Auto)

```
┌─────────────────────────────────────────────────────────────┐
│              pause_sandbox(user_id, project_id)             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────┐
        │  Get sandbox from L1 or reconnect │
        └───────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────┐
        │  Call sandbox.beta_pause()         │
        └───────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────┐
        │  Update Database:                   │
        │  - sandbox_state = PAUSED            │
        │  - updated_at = now()               │
        └───────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────┐
        │  Update Caches:                    │
        │  - Remove from L1 pool             │
        │  - General cache: Keep (30 min)   │
        │  - Long-term cache: Keep (30 days) │
        └───────────────────────────────────┘
```

**Database Update**:
```python
await project_repo.update_sandbox_state(
    project_id=project_id,
    sandbox_id=sandbox_id,  # Keep same sandbox_id
    state=SandboxState.PAUSED
)
```

### 3. Resume Flow

```
┌─────────────────────────────────────────────────────────────┐
│              resume_sandbox(user_id, project_id)             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────┐
        │  Get sandbox_id from:             │
        │  - General cache OR               │
        │  - Long-term cache OR             │
        │  - Database                       │
        └───────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────┐
        │  Check if killed (>30 days):       │
        │  elapsed = now() - project.created_at│
        │  if elapsed > 30 days: KILLED      │
        └───────────────────────────────────┘
                            │
                ┌───────────┴───────────┐
                │                      │
        NOT KILLED              KILLED
                │                      │
                ▼                      ▼
    ┌───────────────────┐    ┌──────────────────┐
    │ Reconnect to      │    │ Create new       │
    │ sandbox           │    │ sandbox          │
    │ (auto-resumes)    │    │                  │
    └───────────────────┘    └──────────────────┘
                │                      │
                └──────────┬───────────┘
                           │
                           ▼
        ┌───────────────────────────────────┐
        │  Update Database:                   │
        │  - sandbox_state = RUNNING          │
        │  - active_sandbox_id = sandbox_id   │
        │  - last_active = now()               │
        └───────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────┐
        │  Update Caches:                    │
        │  - Register in L1 pool             │
        │  - General cache: Update (30 min)  │
        │  - Long-term cache: Keep (30 days) │
        └───────────────────────────────────┘
```

### 4. Cleanup Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    _cleanup_loop()                          │
│                    (runs every 30 seconds)                 │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────┐
        │  For each sandbox in L1 pool:     │
        │  - Check idle timeout             │
        │  - Check max age                  │
        └───────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────┐
        │  For idle/expired sandboxes:      │
        │  - Pause sandbox (E2B)            │
        │  - Update DB: PAUSED              │
        │  - Remove from L1                 │
        │  - Keep in general cache          │
        └───────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────┐
        │  Background: Check DB for killed  │
        │  - Query projects with            │
        │    created_at > 30 days ago      │
        │  - Update sandbox_state = KILLED  │
        │  - Clear long-term cache          │
        └───────────────────────────────────┘
```

---

## Database Integration Points

### 1. Sandbox Creation

```python
async def _create_sandbox_for_user(
    user_id: str, 
    project_id: str, 
    metadata: dict, 
    envs: dict, 
    restore_session: bool = False
):
    """
    Create new sandbox and update DB and caches.
    
    Args:
        restore_session: If True, restore project files/state (for existing projects).
                        If False, create clean sandbox (for completely new sessions).
    """
    # Create sandbox via E2B
    sandbox = await AsyncSandbox.create(...)
    
    # Update database
    await project_repo.update_sandbox_state(
        project_id=project_id,
        sandbox_id=sandbox.sandbox_id,
        state=SandboxState.RUNNING
    )
    
    # Update long-term cache (only if first creation for this project)
    # For completely new sessions (restore_session=False), this is always the first
    # For restoration cases, check if this is the first sandbox
    if not restore_session:
        # Completely new session - always first sandbox
        await self._cache_longterm_sandbox_id(user_id, project_id, sandbox.sandbox_id)
    else:
        # Restoration case - check if first sandbox
        is_first_sandbox = await self._is_first_sandbox_for_project(user_id, project_id)
        if is_first_sandbox:
            await self._cache_longterm_sandbox_id(user_id, project_id, sandbox.sandbox_id)
    
    # Update general cache
    await self._cache_sandbox_id(user_id, project_id, sandbox.sandbox_id, ttl=1800)
    
    # If restoration needed, call restoration route
    if restore_session:
        await self._restore_project_session(sandbox, user_id, project_id)
    
    return sandbox
```

### 2. Sandbox Pause

```python
async def pause_sandbox(...):
    # Pause sandbox
    await sandbox.beta_pause()
    
    # Update database
    await project_repo.update_sandbox_state(
        project_id=project_id,
        sandbox_id=sandbox_id,  # Keep same
        state=SandboxState.PAUSED
    )
    
    # Remove from L1, keep caches
    # ...
```

### 3. Sandbox Resume

```python
async def reconnect_and_register_sandbox(...):
    # Reconnect (auto-resumes)
    sandbox = await AsyncSandbox.connect(sandbox_id, ...)
    
    # Update database
    await project_repo.update_sandbox_state(
        project_id=project_id,
        sandbox_id=sandbox_id,
        state=SandboxState.RUNNING
    )
    
    # Update caches
    # ...
```

### 4. Check if Sandbox is Killed

```python
async def _is_sandbox_killed(project: Project) -> bool:
    """Check if sandbox is killed based on created_at"""
    if not project.active_sandbox_id:
        return False
    
    elapsed_days = (datetime.now() - project.created_at).days
    return elapsed_days > 30
```

### 5. Get Sandbox with DB Fallback

```python
async def get_sandbox(user_id: str, project_id: str, metadata: dict, envs: dict):
    """
    Get sandbox with proper fallback chain:
    L1 → L2 General Cache → Long-Term Cache → DB → Create New
    """
    key = (user_id, project_id)
    
    # Step 1: Check L1 Memory Pool (fastest path)
    if key in self._sandbox_pool:
        sandbox_info = self._sandbox_pool[key]
        return sandbox_info.sandbox
    
    # Step 2: Check L2 General Cache (Redis - 30 min TTL)
    # Acts as safety lock if L1 cache misses
    cached_id = await self._get_cached_sandbox_id(user_id, project_id)
    if cached_id:
        # Cache present = sandbox is paused/running (not killed)
        # Handles both paused and running scenarios
        try:
            sandbox = await self._reconnect_to_sandbox(cached_id, user_id, project_id)
            # Success: Register in L1/L2, update DB, return
            await self._register_sandbox_in_pool(sandbox, user_id, project_id)
            await self._cache_sandbox_id(user_id, project_id, cached_id, ttl=1800)
            await project_repo.update_sandbox_state(
                project_id, cached_id, SandboxState.RUNNING
            )
            return sandbox
        except Exception as e:
            # Connection failed: Proceed to Step 3 (check long-term cache)
            self.logger.warning(f"Failed to reconnect to cached sandbox {cached_id}: {e}")
    
    # Step 3: Check Long-Term Cache (Redis - 30 days TTL)
    longterm_id = await self._get_longterm_sandbox_id(user_id, project_id)
    if longterm_id:
        # Sandbox is probably paused or killed
        # Check DB if killed (>30 days from created_at)
        # Note: Project is always present (created before sandbox request)
        project = await project_repo.get_project(project_id)
        
        if not project:
            # Safety check: If project doesn't exist, fall through to Step 4
            # This should rarely happen, but handle gracefully
            self.logger.warning(f"Project {project_id} not found in DB, proceeding to create new sandbox")
        else:
            is_killed = await self._is_sandbox_killed(project)
            
            if is_killed:
                # Sandbox expired: Mark as KILLED, create new with restoration
                await project_repo.update_sandbox_state(
                    project_id, None, SandboxState.KILLED
                )
                await self._remove_longterm_sandbox_id(user_id, project_id)
                # Create new sandbox + call restoration route
                return await self._create_sandbox_for_user(
                    user_id, project_id, metadata, envs, restore_session=True
                )
            else:
                # Not killed: Try to connect
                try:
                    sandbox = await self._reconnect_to_sandbox(longterm_id, user_id, project_id)
                    await self._register_sandbox_in_pool(sandbox, user_id, project_id)
                    await self._cache_sandbox_id(user_id, project_id, longterm_id, ttl=1800)
                    await project_repo.update_sandbox_state(
                        project_id, longterm_id, SandboxState.RUNNING
                    )
                    return sandbox
                except Exception:
                    # Reconnect failed: Create new with restoration
                    return await self._create_sandbox_for_user(
                        user_id, project_id, metadata, envs, restore_session=True
                    )
    
    # Step 4: Check Database
    # Note: Project is always present (created before sandbox request)
    project = await project_repo.get_project(project_id)
    
    if project and project.active_sandbox_id:
        # Sandbox ID present in DB
        # Check if killed (>30 days from created_at)
        is_killed = await self._is_sandbox_killed(project)
        
        if is_killed:
            # Sandbox expired: Mark as KILLED, create new with restoration
            await project_repo.update_sandbox_state(
                project_id, None, SandboxState.KILLED
            )
            await self._remove_longterm_sandbox_id(user_id, project_id)
            # Create new sandbox + call restoration route
            return await self._create_sandbox_for_user(
                user_id, project_id, metadata, envs, restore_session=True
            )
        else:
            # Not expired: Try to reconnect
            try:
                sandbox = await self._reconnect_to_sandbox(
                    project.active_sandbox_id, user_id, project_id
                )
                await self._register_sandbox_in_pool(sandbox, user_id, project_id)
                await self._cache_sandbox_id(user_id, project_id, project.active_sandbox_id, ttl=1800)
                await project_repo.update_sandbox_state(
                    project_id, project.active_sandbox_id, SandboxState.RUNNING
                )
                return sandbox
            except Exception:
                # Reconnect failed: Create new with restoration
                return await self._create_sandbox_for_user(
                    user_id, project_id, metadata, envs, restore_session=True
                )
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
        return await self._create_sandbox_for_user(
            user_id, project_id, metadata, envs, restore_session=False
        )
```

---

## Redis Cache Keys

### General Cache (Active Sandbox)

```
Key: sandbox:{user_id}:{project_id}
Value: sandbox_id
TTL: 1800 seconds (30 minutes)
Purpose: Fast lookup for active sandboxes
```

### Long-Term Cache (Standby)

```
Key: sandbox:longterm:{user_id}:{project_id}
Value: sandbox_id
TTL: 2592000 seconds (30 days)
Purpose: Maintain sandbox_id for 30-day standby period per project
```

### Paused Marker (Optional)

```
Key: sandbox:paused:{user_id}:{project_id}
Value: "1"
TTL: 604800 seconds (7 days)
Purpose: Quick check if sandbox is manually paused
```

---

## State Synchronization

### Database as Source of Truth

The `Project` table is the **source of truth** for:
1. **Sandbox ID**: `active_sandbox_id` stores the current sandbox
2. **Sandbox State**: `sandbox_state` tracks RUNNING/PAUSED/KILLED/NONE
3. **Lifecycle**: `created_at` determines if sandbox is killed (>30 days)

### Sync Points

| Operation | Database Update | Cache Update |
|-----------|----------------|---------------|
| Create | Set `active_sandbox_id`, `sandbox_state=RUNNING` | Update general + long-term cache |
| Pause | Set `sandbox_state=PAUSED` | Remove from L1, keep caches |
| Resume | Set `sandbox_state=RUNNING`, update `last_active` | Update general cache, register in L1 |
| Cleanup | Set `sandbox_state=PAUSED` | Remove from L1, keep caches |
| Killed | Set `sandbox_state=KILLED`, clear `active_sandbox_id` | Clear long-term cache |

---

## Lifecycle Management

### 30-Day Lifecycle Check

```python
async def _check_sandbox_lifecycle():
    """Background task to check and mark killed sandboxes"""
    # Query projects with sandbox_id and created_at > 30 days ago
    cutoff_date = datetime.now() - timedelta(days=30)
    
    projects = await project_repo.get_projects_with_sandbox_older_than(cutoff_date)
    
    for project in projects:
        if project.sandbox_state != SandboxState.KILLED:
            # Mark as killed
            await project_repo.update_sandbox_state(
                project.id, None, SandboxState.KILLED
            )
            
            # Clear long-term cache
            await self._remove_longterm_sandbox_id(project.user_id, project.id)
```

### Lifecycle States

```
NONE → RUNNING → PAUSED → RUNNING → ... → KILLED
  ↑                                    │
  └────────────────────────────────────┘
   (after 30 days from created_at)
```

---

## Benefits

1. **Persistence**: Sandbox ID survives Redis restarts via database
2. **Lifecycle Management**: Automatic detection of killed sandboxes (>30 days)
3. **State Consistency**: Database ensures state is always accurate
4. **Performance**: Two-layer caching provides fast access
5. **Reliability**: Long-term cache provides fallback when general cache misses
6. **Scalability**: Database can handle millions of projects efficiently

---

## Implementation Checklist

- [ ] Add database queries to `get_sandbox()` method
- [ ] Implement `_is_sandbox_killed()` check
- [ ] Add long-term cache methods (`_cache_longterm_sandbox_id(user_id, project_id, ...)`, etc.)
- [ ] Update `pause_sandbox()` to sync with database
- [ ] Update `resume_sandbox()` to sync with database
- [ ] Update `_create_sandbox_for_user()` to:
  - [ ] Accept `restore_session` parameter
  - [ ] Update database with sandbox_id and state
  - [ ] Update long-term cache (always for new sessions, conditionally for restoration)
  - [ ] Update general cache
  - [ ] Call restoration route if `restore_session=True`
- [ ] Add database fallback in `get_sandbox()` when caches miss:
  - [ ] Check long-term cache (Step 3)
  - [ ] Check database for sandbox_id (Step 4)
  - [ ] Detect completely new session (no long-term cache + no sandbox_id in DB)
  - [ ] Create clean sandbox for new sessions (no restoration)
  - [ ] Create sandbox with restoration for existing projects
- [ ] Add background task for lifecycle checking
- [ ] Update cleanup loop to sync with database
- [ ] Test completely new session scenarios (no cache, no DB sandbox_id)
- [ ] Test 30-day lifecycle scenarios
- [ ] Test Redis restart scenarios
- [ ] Test database as fallback scenarios

---

---

## Completely New Session Detection

### Indicators

A **completely new session** is detected when **both** of these conditions are true:

1. ✅ **No Long-Term Cache**: `sandbox:longterm:{user_id}:{project_id}` does not exist in Redis
2. ✅ **No Sandbox ID in DB**: `Project.active_sandbox_id` is `NULL` or empty

### When This Happens

- First time a user creates a sandbox for a project
- Project exists in DB (created before sandbox request), but no sandbox has been created yet
- All previous sandboxes for this project have been completely removed/expired

### Action Taken

When a completely new session is detected:

1. **Create Clean Sandbox**: Create a fresh sandbox via E2B (no restoration needed)
2. **Update Database**:
   - Set `active_sandbox_id` = new sandbox_id
   - Set `sandbox_state` = RUNNING
   - Update `last_active` = now()
3. **Update Caches**:
   - **L1 Memory Pool**: Register sandbox instance
   - **General Cache**: `sandbox:{uid}:{pid}` → `sandbox_id` (30 min TTL)
   - **Long-Term Cache**: `sandbox:longterm:{uid}:{pid}` → `sandbox_id` (30 days TTL) - **Always set for new sessions**

### Difference from Restoration

| Scenario | Indicators | Action |
|----------|-----------|--------|
| **Completely New Session** | No long-term cache + No sandbox_id in DB | Create clean sandbox, no restoration |
| **Session Restoration** | Long-term cache exists OR sandbox_id in DB (but killed/expired) | Create sandbox + restore project files/state |

### Code Flow

```python
# Step 3: Check Long-Term Cache
longterm_id = await self._get_longterm_sandbox_id(user_id, project_id)
if not longterm_id:
    # No long-term cache - proceed to DB check
    
    # Step 4: Check Database
    project = await project_repo.get_project(project_id)
    if project and not project.active_sandbox_id:
        # ✅ COMPLETELY NEW SESSION DETECTED
        # Indicators:
        # - No long-term cache (checked above)
        # - No sandbox_id in DB (current check)
        
        # Create clean sandbox (no restoration)
        return await self._create_sandbox_for_user(
            user_id, project_id, metadata, envs, restore_session=False
        )
```

---

*Last Updated: 2024*

