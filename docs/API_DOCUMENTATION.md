# Landing Page Generation Python Backend - API Documentation

This document provides comprehensive API documentation for the Python landing page generation backend. This documentation is intended for NestJS integration.

**Base URL**: `http://localhost:8000` (or your deployed Python backend URL)

**Content-Type**: `application/json` (unless specified otherwise)

**Streaming**: The `/chat` endpoint uses Server-Sent Events (SSE) with `text/event-stream` content type.

---

## Table of Contents

1. [Health & Status Endpoints](#health--status-endpoints)
2. [Chat/Agent Endpoints](#chatagent-endpoints)
3. [Project Management Endpoints](#project-management-endpoints)
4. [Asset Upload/Processing Endpoints](#asset-uploadprocessing-endpoints)
5. [Sandbox Management Endpoints](#sandbox-management-endpoints)
6. [ZIP Download Endpoints](#zip-download-endpoints)

---

## Health & Status Endpoints

### GET `/health`

Check if the API is running.

**Response:**
```json
{
  "status": "ok"
}
```

**Status Codes:**
- `200 OK`: Service is healthy

---

### GET `/`

Root endpoint that returns a simple message.

**Response:**
```json
{
  "message": "Landing Page Generation API is running"
}
```

**Status Codes:**
- `200 OK`: Service is running

---

## Chat/Agent Endpoints

### POST `/chat`

Chat with the AI agent using streaming response (Server-Sent Events).

**Description:**
- Supports multiple model providers (OpenAI, Anthropic, Google GenAI, OpenRouter)
- Returns streaming responses via Server-Sent Events (SSE)
- Maintains conversation history using `project_id` as thread_id
- Supports vision models with image URLs
- Supports document context for RAG

**Request Body:**
```json
{
  "message": "Create a simple React app with a counter",
  "project_id": "project_123",  // Required: Used as session_id/thread_id
  "user_id": "user_456",         // Optional: Defaults to "default-user"
  "model": "x-ai/grok-4-fast",   // Optional: Default model
  "model_provider": "openrouter", // Optional: "openai" | "anthropic" | "google_genai" | "openrouter"
  "streaming": true,              // Optional: Default true
  "temperature": 0.5,             // Optional: Default 0.5
  "timeout": 300,                // Optional: Default 300 (5 minutes)
  "max_tokens": 1000,            // Optional: Default 1000
  "image_urls": [                // Optional: For vision models
    "https://example.com/image1.png",
    "https://example.com/image2.jpg"
  ],
  "document_context": [           // Optional: Document summaries for context
    {
      "filename": "script.py",
      "type": "py",
      "summary": "This Python script implements file operations..."
    }
  ]
}
```

**Response Format:**
Server-Sent Events (SSE) stream with the following event types:

1. **`agent_start`** - Agent processing started
```json
{
  "event": "agent_start",
  "data": {
    "timestamp": "2025-01-03T10:30:00.000Z",
    "project_id": "project_123",
    "user_id": "user_456"
  }
}
```

2. **`tool_start`** - Tool execution started
```json
{
  "event": "tool_start",
  "data": {
    "tool_name": "create_file",
    "tool_id": "call_abc123",
    "tool_args": {"path": "src/App.js", "content": "..."},
    "node": "agent"
  }
}
```

3. **`tool_complete`** - Tool execution completed
```json
{
  "event": "tool_complete",
  "data": {
    "tool_name": "create_file",
    "output_preview": "File created successfully...",
    "node": "agent"
  }
}
```

4. **`agent_thinking`** - LLM token stream
```json
{
  "event": "agent_thinking",
  "data": {
    "token": "I'll create",
    "node": "agent"
  }
}
```

5. **`agent_complete`** - Agent processing completed
```json
{
  "event": "agent_complete",
  "data": {
    "timestamp": "2025-01-03T10:30:05.000Z",
    "project_id": "project_123",
    "usage_metadata": {},
    "token_summary": {
      "total_input": 150,
      "total_output": 500,
      "total_cost": 0.0025,
      "by_model": {
        "grok-4-fast": {
          "input": 150,
          "output": 500,
          "cost": 0.0025
        }
      }
    },
    "model_provider": "openrouter",
    "model_name": "x-ai/grok-4-fast",
    "timing": {
      "total_duration_ms": 5234.56,
      "first_response_ms": 1234.56,
      "start_time": "2025-01-03T10:30:00.000Z",
      "end_time": "2025-01-03T10:30:05.000Z"
    }
  }
}
```

6. **`error`** - Error occurred
```json
{
  "event": "error",
  "data": {
    "message": "Error description",
    "type": "ErrorType",
    "timestamp": "2025-01-03T10:30:00.000Z",
    "suggestion": "Optional suggestion"
  }
}
```

**Headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

**Status Codes:**
- `200 OK`: Stream started successfully
- `400 Bad Request`: Invalid request parameters
- `500 Internal Server Error`: Agent execution error

**Model Provider Options:**
- `"openai"`: OpenAI models (requires `OPENAI_API_KEY`)
- `"anthropic"`: Anthropic Claude models (requires `ANTHROPIC_API_KEY`)
- `"google_genai"`: Google Gemini models (requires `GOOGLE_API_KEY`)
- `"openrouter"`: OpenRouter models (requires `OPENROUTER_API_KEY`)

**Notes:**
- `project_id` is used as both `thread_id` (for conversation persistence) and `session_id` (for memory context)
- For OpenRouter, the API automatically sets `base_url` to `https://openrouter.ai/api/v1`
- Image URLs should be publicly accessible or signed URLs
- Document context should be provided by NestJS from `Project.metadata.documents[]`

---

## Project Management Endpoints

### GET `/projects/{project_id}/history`

Get conversation history for a project.

**Path Parameters:**
- `project_id` (string, required): The project ID (used as session_id/thread_id)

**Query Parameters:**
- `limit` (integer, optional): Maximum number of checkpoints to retrieve (default: 50)

**Response:**
```json
{
  "project_id": "project_123",
  "count": 10,
  "history": [
    {
      "checkpoint_id": "checkpoint_1",
      "timestamp": "2025-01-03T10:30:00.000Z",
      "messages": [...],
      "metadata": {...}
    }
  ]
}
```

**Status Codes:**
- `200 OK`: History retrieved successfully
- `400 Bad Request`: Invalid project_id
- `503 Service Unavailable`: Checkpointer not initialized
- `500 Internal Server Error`: Failed to retrieve history

---

### GET `/projects/{project_id}/state`

Get current state for a project.

**Path Parameters:**
- `project_id` (string, required): The project ID (used as session_id/thread_id)

**Response:**
```json
{
  "project_id": "project_123",
  "state": {
    "checkpoint_id": "checkpoint_1",
    "messages": [...],
    "metadata": {...}
  }
}
```

Or if no state exists:
```json
{
  "project_id": "project_123",
  "state": null,
  "message": "No state found for this project"
}
```

**Status Codes:**
- `200 OK`: State retrieved successfully
- `503 Service Unavailable`: Checkpointer not initialized
- `500 Internal Server Error`: Failed to retrieve state

---

### DELETE `/projects/{project_id}`

Delete all history for a project.

**Path Parameters:**
- `project_id` (string, required): The project ID to delete

**Response:**
```json
{
  "project_id": "project_123",
  "deleted": true,
  "message": "Project history deleted successfully"
}
```

**Status Codes:**
- `200 OK`: Project history deleted successfully
- `400 Bad Request`: Invalid project_id
- `503 Service Unavailable`: Checkpointer not initialized
- `500 Internal Server Error`: Failed to delete history

---

### GET `/api/sandboxes/paused`

List all paused sandboxes.

**Response:**
```json
{
  "count": 2,
  "sandboxes": [
    {
      "sandbox_id": "sandbox_123",
      "user_id": "user_456",
      "project_id": "project_123",
      "status": "paused",
      "paused_at": "2025-01-03T10:30:00.000Z"
    }
  ]
}
```

**Status Codes:**
- `200 OK`: List retrieved successfully
- `400 Bad Request`: Invalid request
- `500 Internal Server Error`: Failed to list sandboxes

---

## Asset Upload/Processing Endpoints

**Base Path:** `/assets`

**Architecture Note:**
- Python backend handles file processing (document/image analysis, RAG embeddings)
- NestJS backend handles file upload to S3 and metadata storage
- Flow: NestJS uploads to S3 → calls Python with S3 URL → Python processes → returns structured results → NestJS stores metadata

---

### POST `/assets/process-document`

Process a document file from S3 URL.

**Description:**
- Downloads document from S3
- Generates summary
- Chunks document
- Stores embeddings in MongoDB (RAG ready)
- Returns structured result for NestJS to store in `Project.metadata.documents[]`

**Request Body (JSON):**
```json
{
  "document": {
    "filename": "document.pdf",
    "filetype": ".pdf",
    "public_url": "https://s3.amazonaws.com/bucket/file.pdf",
    "metadata": {
      "file_size": 12345,
      "uploaded_at": "2026-01-12T10:00:00Z"
    }
  },
  "project_id": "project_123",  // Required: Project ID (used internally as session_id/thread_id)
  "user_id": "user_456"           // Required: User ID
}
```

**Response:**
```json
{
  "success": true,
  "asset_id": "uuid-generated-id",
  "filename": "document.pdf",
  "s3_url": "https://s3.amazonaws.com/bucket/file.pdf",
  "file_type": "pdf",
  "language": null,  // For code files: "python", "javascript", etc.
  "is_code_file": false,
  "summary": "This document contains information about...",
  "total_chunks": 8,
  "token_count": 6709,
  "rag_processed": true,
  "error": null,
  "message": "Document processed successfully: document.pdf"
}
```

**Error Response:**
```json
{
  "success": false,
  "asset_id": "uuid-generated-id",
  "filename": "document.pdf",
  "s3_url": "https://s3.amazonaws.com/bucket/file.pdf",
  "file_type": "pdf",
  "is_code_file": false,
  "summary": "",
  "total_chunks": 0,
  "token_count": 0,
  "rag_processed": false,
  "error": "Error message here",
  "message": "Document processing failed: Error message here"
}
```

**Status Codes:**
- `200 OK`: Processing completed (check `success` field)
- `400 Bad Request`: Missing required parameters
- `500 Internal Server Error`: Processing failed

**Supported Document Types:**
- PDF: `.pdf`
- Word: `.docx`, `.doc`
- Text: `.txt`, `.md`
- Code: `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.java`, `.cpp`, `.c`, `.go`, `.rs`, `.rb`, `.php`, `.swift`, `.kt`
- Web: `.html`, `.css`, `.json`, `.xml`, `.yaml`, `.yml`
- Spreadsheets: `.csv`, `.xlsx`
- Presentations: `.pptx`

---

### POST `/assets/process-image`

Process an image file from S3 URL.

**Description:**
- Downloads image from S3
- Analyzes with vision model
- Stores embedding in MongoDB (RAG ready)
- Returns structured result for NestJS to store in `Project.metadata.images[]`

**Request Body (Query Parameters or JSON):**
```json
{
  "s3_url": "https://s3.amazonaws.com/bucket/image.png",  // Required
  "filename": "screenshot.png",                           // Required
  "project_id": "project_123",                            // Required: Project ID (used internally as session_id)
  "content_type": "image/png"                             // Optional: MIME type
}
```

**Response:**
```json
{
  "success": true,
  "asset_id": "uuid-generated-id",
  "filename": "screenshot.png",
  "s3_url": "https://s3.amazonaws.com/bucket/image.png",
  "image_url": "https://s3.amazonaws.com/bucket/image.png",  // Same as s3_url
  "analysis": "Image Type: design\nPurpose: dashboard\nComponents: navbar, sidebar, main content...",
  "rag_processed": true,
  "error": null,
  "message": "Image processed successfully: screenshot.png"
}
```

**Error Response:**
```json
{
  "success": false,
  "asset_id": "uuid-generated-id",
  "filename": "screenshot.png",
  "s3_url": "https://s3.amazonaws.com/bucket/image.png",
  "image_url": "https://s3.amazonaws.com/bucket/image.png",
  "analysis": "",
  "rag_processed": false,
  "error": "Error message here",
  "message": "Image processing failed: Error message here"
}
```

**Status Codes:**
- `200 OK`: Processing completed (check `success` field)
- `400 Bad Request`: Missing required parameters
- `500 Internal Server Error`: Processing failed

**Supported Image Types:**
- `.jpg`, `.jpeg`, `.png`, `.gif`, `.svg`, `.webp`, `.bmp`

---

### ~~POST `/assets/process-asset`~~ (DEPRECATED - Commented Out)

**⚠️ This endpoint is currently commented out due to ambiguity concerns.**

**Use instead:**
- `/assets/process-document` for documents
- `/assets/process-image` for images

This provides clearer, more explicit processing with proper request models.

---

## Sandbox Management Endpoints

**Base Path:** `/api/sandbox`

**Architecture Note:**
- E2B sandbox sessions are managed per `user_id` and `project_id`
- **Two-layer Redis caching**: General cache (30 min TTL) + Long-term cache (30 days TTL)
- **Database integration**: PostgreSQL `Project` table serves as source of truth
- **30-day lifecycle**: E2B beta sandboxes are valid for 30 days (auto-deleted after)
- **Automatic session restoration**: Restores project files/state when creating new sandbox for existing project
- Supports pausing/resuming sandboxes with state synchronization
- Provides public URLs for ports 3000 (frontend) and 8000 (backend)

**Four-Step Retrieval Flow:**
1. **Memory pool (L1)**: Instant access for active sandboxes
2. **General cache (Redis 30 min)**: Recently used sandboxes
3. **Long-term cache (Redis 30 days)**: Paused/standby sandboxes
4. **Database (PostgreSQL)**: Permanent source of truth for sandbox state

---

### POST `/api/sandbox/session`

Get or create sandbox session for user_id and project_id.

**Description:**
This is the **PRIMARY endpoint** for sandbox management. It intelligently:
- Returns existing sandbox if found (from memory, cache, or database)
- Creates new sandbox only if needed
- Automatically resumes paused sandboxes
- Handles session restoration for existing projects
- Detects completely new sessions vs. existing projects needing restoration

**Features:**
- Two-layer Redis caching for performance
- Database as source of truth
- 30-day sandbox lifecycle management
- Automatic session restoration
- Graceful handling of missing database records

**Use this endpoint for:**
- Initial sandbox creation
- Reconnecting to existing sandboxes
- Resuming paused sandboxes
- General sandbox retrieval

**Request Body:**
```json
{
  "user_id": "user_456",      // Required
  "project_id": "project_123" // Required
}
```

**Response:**
```json
{
  "success": true,
  "sandbox_id": "sandbox_abc123",
  "user_id": "user_456",
  "project_id": "project_123",
  "frontend_url": "https://3000-sandbox_abc123.e2b.app",
  "backend_url": "https://8000-sandbox_abc123.e2b.app",
  "message": "Sandbox session created/retrieved successfully"
}
```

**Status Codes:**
- `200 OK`: Sandbox created/retrieved successfully
- `400 Bad Request`: Invalid request parameters
- `500 Internal Server Error`: Failed to create session

**Notes:**
- In production, NestJS should create the project in the database before calling this endpoint
- If project doesn't exist in DB, a temporary project may be created for testing (will be removed in production)
- Sandbox state is automatically synchronized with the database
- Killed sandboxes (>30 days old) are automatically detected and replaced

---

### POST `/api/sandbox/pause`

Pause sandbox session and optionally update expiration time.

**Description:**
Pauses the sandbox and manages caching/storage layers:
- Pauses the sandbox (saves state, stops billing)
- Removes from L1 memory pool (saves memory)
- Removes from general cache (30 min TTL)
- **Keeps in long-term cache (30 days) for recovery**
- **Updates database state to PAUSED**
- Optionally updates the timeout/expiration time before pausing

**Recovery:**
- Sandbox can be resumed via long-term cache (30 days)
- Database maintains state for persistence beyond cache expiry

**Request Body:**
```json
{
  "user_id": "user_456",           // Required
  "project_id": "project_123",     // Required
  "timeout": 3600                   // Optional: New timeout in seconds before pausing
}
```

**Note:** `user_id` and `project_id` are required for proper state management and database synchronization. The `sandbox_id` parameter is not needed as it will be looked up.

**Response:**
```json
{
  "success": true,
  "sandbox_id": "sandbox_abc123",
  "paused": true,
  "timeout": 3600,
  "message": "Sandbox sandbox_abc123 paused successfully. Recoverable via long-term cache (30 days) or database."
}
```

**Status Codes:**
- `200 OK`: Sandbox paused successfully
- `400 Bad Request`: Invalid parameters (timeout must be positive, or missing user_id/project_id)
- `404 Not Found`: Sandbox not found
- `500 Internal Server Error`: Failed to pause session

---

### POST `/api/sandbox/resume`

Resume sandbox session (alias for `/session` endpoint with explicit intent).

**Description:**
This endpoint uses the same intelligent retrieval as `/session`:
- Checks all sources (memory, general cache, long-term cache, database)
- Automatically resumes paused sandboxes
- Reconnects to existing sandboxes
- Creates new if sandbox doesn't exist anymore

**Note:** Since `get_sandbox()` handles everything (reconnect, resume, create), this endpoint is functionally equivalent to `/session`. It exists for:
- Semantic clarity (explicit "resume" intent)
- Backward compatibility
- Different response format

**For new integrations, prefer `/session` endpoint.**

**Request Body:**
```json
{
  "user_id": "user_456",           // Required
  "project_id": "project_123"      // Required
}
```

**Response:**
```json
{
  "success": true,
  "sandbox_id": "sandbox_abc123",
  "resumed": true,
  "message": "Sandbox sandbox_abc123 ready (resumed/reconnected)"
}
```

**Status Codes:**
- `200 OK`: Sandbox resumed/reconnected successfully
- `400 Bad Request`: Missing required parameters (user_id/project_id)
- `500 Internal Server Error`: Failed to resume session

---

### GET `/api/sandbox/public-url`

Get public URL for a specific port (3000 or 8000) on the sandbox.

**Query Parameters:**
- `user_id` (string, required): User ID
- `project_id` (string, required): Project ID
- `port` (integer, required): Port number (3000 or 8000)

**Response:**
```json
{
  "success": true,
  "sandbox_id": "sandbox_abc123",
  "port": 3000,
  "public_url": "https://3000-sandbox_abc123.e2b.app",
  "message": "Public URL retrieved successfully for port 3000"
}
```

**Status Codes:**
- `200 OK`: URL retrieved successfully
- `400 Bad Request`: Invalid port (only 3000 and 8000 supported)
- `500 Internal Server Error`: Failed to get public URL

---

### GET `/api/sandbox/public-urls`

Get public URLs for both ports 3000 and 8000.

**Query Parameters:**
- `user_id` (string, required): User ID
- `project_id` (string, required): Project ID

**Response:**
```json
{
  "success": true,
  "sandbox_id": "sandbox_abc123",
  "urls": {
    "port_3000": "https://3000-sandbox_abc123.e2b.app",
    "port_8000": "https://8000-sandbox_abc123.e2b.app"
  },
  "errors": null,
  "message": "Public URLs retrieved successfully"
}
```

**Error Response (partial failure):**
```json
{
  "success": false,
  "sandbox_id": "sandbox_abc123",
  "urls": {
    "port_3000": "https://3000-sandbox_abc123.e2b.app"
  },
  "errors": {
    "port_8000": "Port not available"
  },
  "message": "Some URLs could not be retrieved"
}
```

**Status Codes:**
- `200 OK`: URLs retrieved (check `success` and `errors` fields)
- `500 Internal Server Error`: Failed to get URLs

---

### GET `/api/sandbox/status`

Get status of sandbox session.

**Description:**
Returns information about the sandbox including connection status and cache state.

**Note:** This endpoint checks only the general cache (30 min TTL). Full status including long-term cache (30 days) and database requires additional queries or using the `/session` endpoint.

**Query Parameters:**
- `user_id` (string, required): User ID
- `project_id` (string, required): Project ID
- `sandbox_id` (string, optional): Sandbox ID (if provided, takes priority)

**Response (Active):**
```json
{
  "success": true,
  "exists": true,
  "sandbox_id": "sandbox_abc123",
  "status": "active",
  "in_redis": true,
  "message": "Sandbox is active and responsive"
}
```

**Response (Not Found):**
```json
{
  "success": true,
  "exists": false,
  "message": "No sandbox found for this user/project"
}
```

**Response (Error):**
```json
{
  "success": true,
  "exists": true,
  "sandbox_id": "sandbox_abc123",
  "status": "error",
  "error": "Connection timeout",
  "message": "Sandbox exists but is not responsive"
}
```

**Status Codes:**
- `200 OK`: Status retrieved successfully
- `500 Internal Server Error`: Failed to get status

---

## ZIP Download Endpoints

**Base Path:** `/api/projects`

**Architecture Note:**
- Creates ZIP archives from sandbox file system
- Supports full project, specific folders, or custom paths
- Returns signed download URLs with expiration
- ZIP files are stored in sandbox at `/home/user/code/`

---

### POST `/api/projects/{project_id}/download`

Create and download ZIP archive with flexible path options.

**Description:**
- Universal endpoint for all download scenarios
- Handles full project, specific folders, or custom paths
- Returns signed download URL (E2B sandbox URL with signature)
- Supports custom exclusion patterns

**Path Parameters:**
- `project_id` (string, required): Project identifier

**Request Body:**
```json
{
  "user_id": "user_456",                    // Required
  "source_path": "frontend",                // Optional: None = full project, relative/absolute paths supported
  "zip_name": "my_project_v1.zip",          // Optional: Auto-generated if None
  "exclude_patterns": ["*.log", "*.tmp"],   // Optional: Custom exclusion patterns
  "use_defaults": true,                     // Optional: Merge with default excludes (node_modules, .git, etc.)
  "url_expiration": 3600                    // Optional: URL expiration in seconds (default: 10000)
}
```

**Examples:**

1. **Full project:**
```json
{
  "user_id": "user_456"
}
```

2. **Frontend folder:**
```json
{
  "user_id": "user_456",
  "source_path": "frontend"
}
```

3. **Backend with custom excludes:**
```json
{
  "user_id": "user_456",
  "source_path": "backend",
  "exclude_patterns": ["*.pyc", "venv/*"],
  "use_defaults": true
}
```

4. **Custom expiration:**
```json
{
  "user_id": "user_456",
  "source_path": "frontend",
  "url_expiration": 3600
}
```

**Response:**
```json
{
  "success": true,
  "download_url": "https://sandbox_abc123.e2b.app/files/download?path=/home/user/code/project.zip&signature=...",
  "filename": "project_20250103_103000.zip",
  "source_path": "/home/user/code/frontend",
  "is_full_project": false,
  "size_bytes": 5242880,
  "size_mb": 5.0,
  "created_at": "2025-01-03T10:30:00.000Z",
  "expires_at": "2025-01-03T13:30:00.000Z",
  "sandbox_path": "/home/user/code/project_20250103_103000.zip",
  "user_id": "user_456",
  "project_id": "project_123"
}
```

**Status Codes:**
- `200 OK`: ZIP created successfully
- `400 Bad Request`: Invalid path or parameters
- `403 Forbidden`: Permission denied
- `404 Not Found`: Path not found in sandbox
- `500 Internal Server Error`: ZIP creation failed

**Path Handling:**
- `source_path: null` or omitted = Full project (`/home/user/code`)
- `source_path: "frontend"` = Relative to `/home/user/code/frontend`
- `source_path: "/home/user/code/backend"` = Absolute path (used as-is)

**Default Exclusion Patterns:**
- `node_modules/`, `.git/`, `.venv/`, `venv/`, `__pycache__/`, `*.pyc`, `.env`, `.DS_Store`, etc.

---

### GET `/api/projects/{project_id}/download/list-zips`

List all existing ZIP files in the sandbox.

**Path Parameters:**
- `project_id` (string, required): Project identifier

**Query Parameters:**
- `user_id` (string, required): User identifier

**Response:**
```json
{
  "success": true,
  "project_id": "project_123",
  "zip_count": 3,
  "zip_files": [
    {
      "path": "/home/user/code/project_20250103_103000.zip",
      "filename": "project_20250103_103000.zip",
      "size_bytes": 5242880,
      "size_mb": 5.0,
      "created_at": "2025-01-03T10:30:00.000Z"
    }
  ]
}
```

**Status Codes:**
- `200 OK`: List retrieved successfully
- `500 Internal Server Error`: Failed to list ZIP files

---

### DELETE `/api/projects/{project_id}/download/cleanup`

Delete specific or all ZIP files to free sandbox space.

**Path Parameters:**
- `project_id` (string, required): Project identifier

**Query Parameters:**
- `user_id` (string, required): User identifier
- `sandbox_path` (string, optional): Specific ZIP path to delete (None = delete all)

**Response (Delete specific):**
```json
{
  "success": true,
  "message": "ZIP file deleted",
  "deleted_path": "/home/user/code/project_20250103_103000.zip"
}
```

**Response (Delete all):**
```json
{
  "success": true,
  "message": "Deleted 3 ZIP files",
  "deleted_count": 3,
  "total_count": 3
}
```

**Status Codes:**
- `200 OK`: Cleanup completed successfully
- `500 Internal Server Error`: Failed to cleanup ZIPs

---

## Error Handling

All endpoints follow consistent error response format:

```json
{
  "detail": "Error message description"
}
```

**Common Status Codes:**
- `400 Bad Request`: Invalid request parameters
- `404 Not Found`: Resource not found
- `500 Internal Server Error`: Server error
- `503 Service Unavailable`: Service not initialized (checkpointer, etc.)

---

## Integration Notes for NestJS

### 1. Chat Endpoint Integration

**SSE Client Setup:**
```typescript
const eventSource = new EventSource(
  `${PYTHON_BACKEND_URL}/chat`,
  {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message: userMessage,
      project_id: projectId,
      user_id: userId,
      image_urls: project.metadata.images.map(img => img.s3_url),
      document_context: project.metadata.documents.map(doc => ({
        filename: doc.filename,
        type: doc.file_type,
        summary: doc.summary
      }))
    })
  }
);

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // Handle different event types
};
```

### 2. Asset Processing Flow

1. NestJS uploads file to S3 → gets S3 URL
2. NestJS calls Python backend: `POST /assets/process-asset`
3. Python processes file → returns structured results
4. NestJS stores metadata in `Project.metadata.documents[]` or `Project.metadata.images[]`
5. When sending chat request, NestJS extracts asset context from metadata

### 3. Project Metadata Structure

Store asset processing results in your Project model:

```typescript
{
  metadata: {
    documents: [
      {
        asset_id: "uuid",
        filename: "script.py",
        s3_url: "https://...",
        file_type: "py",
        language: "python",
        is_code_file: true,
        summary: "...",
        total_chunks: 8,
        token_count: 6709,
        rag_processed: true,
        added_at: "2025-01-03T10:30:00Z"
      }
    ],
    images: [
      {
        asset_id: "uuid",
        filename: "dashboard.png",
        s3_url: "https://...",
        image_url: "https://...",
        analysis: "...",
        rag_processed: true,
        added_at: "2025-01-03T10:30:00Z"
      }
    ]
  }
}
```

### 4. Sandbox Session Management

**Database Integration:**
- Projects should be created in the database **before** calling sandbox endpoints
- The Python backend will automatically sync sandbox state to `Project.active_sandbox_id` and `Project.sandbox_state`
- Sandbox state values: `NONE`, `RUNNING`, `PAUSED`, `KILLED`

**Recommended Flow:**
1. Create project in DB: NestJS creates `Project` record with `sandbox_state = NONE`
2. Create/get sandbox: `POST /api/sandbox/session` (automatically updates DB with `sandbox_id` and `RUNNING` state)
3. Pause sandbox when user is inactive: `POST /api/sandbox/pause` (updates DB to `PAUSED` state)
4. Resume sandbox when user returns: `POST /api/sandbox/resume` or `POST /api/sandbox/session` (updates DB to `RUNNING` state)
5. Get public URLs for frontend/backend: `GET /api/sandbox/public-urls`

**Caching Strategy:**
- **General cache (30 min)**: Fast retrieval for recently used sandboxes
- **Long-term cache (30 days)**: Standby cache for paused/expired sandboxes
- **Database**: Permanent source of truth, survives Redis restarts

**Lifecycle Management:**
- E2B beta sandboxes are automatically deleted after 30 days
- The system automatically detects killed sandboxes (based on `Project.created_at`)
- When a sandbox is killed, a new one is created with session restoration (if project files exist)

### 5. Environment Variables

Python backend requires:
- `OPENAI_API_KEY` (for OpenAI models)
- `ANTHROPIC_API_KEY` (for Anthropic models)
- `GOOGLE_API_KEY` (for Google GenAI models)
- `OPENROUTER_API_KEY` (for OpenRouter models)
- `MONGODB_URI` (for checkpointer and RAG)
- `E2B_API_KEY` (for sandbox management)
- `REDIS_URL` (for sandbox caching - two-layer: general + long-term)
- `DATABASE_URL` (PostgreSQL connection string for project state management)

---

## Version Information

**API Version:** 1.0.0

**Last Updated:** 2025-01-03

---

## Support

For issues or questions, please refer to the main application documentation or contact the development team.

