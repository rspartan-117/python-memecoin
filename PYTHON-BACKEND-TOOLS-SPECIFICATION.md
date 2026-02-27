# Python Backend Tools Specification

This document provides a comprehensive specification of all NestJS backend services that need to be implemented as production-ready tools/endpoints in the Python backend. Each service is documented with its purpose, key methods, API interactions, and implementation requirements.

---

## Table of Contents

1. [Generation Services](#1-generation-services)
   - [1.1 Image/Text Generation Service](#11-imagetext-generation-service)
   - [1.2 Brand Data Service](#12-brand-data-service)
   - [1.3 Background Removal Service](#13-background-removal-service)
2. [Project Management Services](#2-project-management-services)
   - [2.1 Projects Service](#21-projects-service)
   - [2.2 Sandbox Service](#22-sandbox-service)
   - [2.3 Chat Service](#23-chat-service)
   - [2.4 Assets Service](#24-assets-service)
   - [2.5 Files Service](#25-files-service)
   - [2.6 Download Service](#26-download-service)
3. [User & Credits Management](#3-user--credits-management)
   - [3.1 Users Service](#31-users-service)
   - [3.2 Credits Management Service](#32-credits-management-service)
   - [3.3 Coupons Service](#33-coupons-service)
4. [Infrastructure Services](#4-infrastructure-services)
   - [4.1 S3/Storage Service](#41-s3storage-service)
   - [4.2 E2B Webhook Service](#42-e2b-webhook-service)
5. [Implementation Priorities](#5-implementation-priorities)

---

## 1. Generation Services

### 1.1 Image/Text Generation Service

**Purpose**: AI-powered content generation supporting text and image generation using multiple AI providers (OpenAI, Google Gemini, Fal.ai) with automatic S3 storage integration.

#### Key Features
- Multi-provider support for image generation (DALL-E 3, Fal.ai models)
- Text-to-image generation with various models
- Image-to-image transformations
- Synchronous generation with credit management
- Automatic S3 upload and storage
- Real-time credit deduction and refund on failure
- Background removal support

#### Core Methods to Implement

**1. `generateWithCredits(userId, modelName, params, options)`**
- **Purpose**: Main production method for LLM tools - synchronous generation with automatic credit management
- **Process Flow**:
  1. Validate user has enough credits
  2. Submit to Fal AI API FIRST (before deducting credits)
  3. Deduct credits only after successful submission
  4. Wait for completion (optional)
  5. Automatically refund on failure
  6. Upload result to S3
  7. Return result with URLs and credit info

- **Parameters**:
  - `userId`: User identifier
  - `modelName`: AI model name (e.g., "fal-ai/flux/schnell", "dall-e-3")
  - `params`: Generation parameters (prompt, size, quality, etc.)
  - `options`:
    - `waitForCompletion`: Boolean (default: true)
    - `timeoutMs`: Max wait time (default: 300000)

- **Returns**:
```typescript
{
  success: boolean,
  assetId: string,
  imageUrl?: string,
  creditsUsed: number,
  creditsRemaining: number,
  model: string,
  error?: string,
  metadata?: {
    width?: number,
    height?: number,
    format?: string,
    seed?: number
  }
}
```

**2. `textToImage(userId, modelName, prompt, params, options)`**
- Text prompt → Generated image
- Supports multiple models from config
- Returns S3 URL and asset ID

**3. `imageToImage(userId, modelName, imageUrl, prompt, params, options)`**
- Image + prompt → Transformed image
- Supports models like flux-pro, flux-dev, etc.
- Returns new image URL

**4. `removeBackground(userId, imageUrl, options)`**
- Remove background from image
- Uses fal-ai/imageutils/rembg model
- Returns transparent PNG with S3 URL
- Cost: 2 credits per operation
- Options:
  - `sync_mode`: Boolean
  - `crop_to_bbox`: Boolean
  - `waitForCompletion`: Boolean
  - `timeoutMs`: Number

**5. `pollJobStatus(requestId, timeoutMs)`**
- Poll Fal AI for job completion
- Exponential backoff polling
- Return final result or timeout

#### S3 Integration Requirements
- Automatic upload of all generated images
- File organization: `generated/images/{userId}/{timestamp}_{sanitized_prompt}.png`
- Support both public and private URLs
- Presigned URL generation for private files
- Metadata tracking (original Fal URLs, dimensions, etc.)

#### Credit Management
- Pre-check user credits before generation
- Atomic credit deduction (transaction-safe)
- Automatic refund on failure
- Track credit usage per model
- Real-time credit balance updates

#### Models Registry
The service should support dynamic model configuration from a registry:
- Text-to-image models (DALL-E 3, Flux variants, etc.)
- Image-to-image models (Flux Pro, Flux Dev, etc.)
- Model metadata (cost, capabilities, parameters)

#### Error Handling
- Invalid model name
- Insufficient credits
- Fal API failures
- S3 upload failures
- Timeout handling
- Automatic cleanup on failure

---

### 1.2 Brand Data Service

**Purpose**: Integration with Brand.dev API to retrieve brand assets (logos, colors, fonts, metadata) and AI-powered data extraction from company websites.

#### Key Features
- Brand asset retrieval (logos, colors, fonts)
- AI-powered website data extraction
- In-memory caching (1-hour TTL)
- Domain normalization
- Multiple logo sizes and formats
- Health monitoring and cache statistics

#### Core Methods to Implement

**1. `getBrandData(domain, options)`**
- Fetch comprehensive brand data for a domain
- Parameters:
  - `domain`: Company domain (e.g., "uniswap.org")
  - `forceRefresh`: Bypass cache (optional)
  - `maxSpeed`: Optimize for speed (optional)
  - `force_language`: Force specific language (optional)
  - `timeoutMS`: Request timeout (optional, max 300000)

- **Returns**:
```typescript
{
  success: boolean,
  brand?: {
    domain: string,
    title: string,
    description: string,
    colors: Array<{hex: string, name: string}>,
    logos: Array<{url: string, type: string, mode: string, resolution: {width: number, height: number}}>,
    fonts: Array<{name: string, weight: string}>,
    links: {
      careers?: string,
      blog?: string,
      pricing?: string,
      // ... more links
    }
  },
  colors: string[],
  logos: string[],
  description?: string,
  cached: boolean,
  timestamp: Date,
  error?: string
}
```

**2. `aiQuery(domain, query, options)`**
- Extract custom data points from any website using AI
- Parameters:
  - `domain`: Target domain
  - `query`: Natural language query (e.g., "What is their pricing model?")
  - `maxSpeed`: Boolean (optional)
  - `timeoutMS`: Number (optional)

- **Returns**:
```typescript
{
  success: boolean,
  result?: string,
  query: string,
  domain: string,
  timestamp: Date,
  error?: string
}
```

**3. `normalizeDomain(domain)`**
- Clean and normalize domain names
- Remove http/https, www, trailing slashes
- Handle subdomains

**4. `getCachedBrand(domain)`**
- Check in-memory cache
- Return cached data if valid (< 1 hour old)

**5. `cleanupCache()`**
- Periodic cleanup of expired cache entries
- Run every hour

#### Caching Strategy
- In-memory cache with Map structure
- Cache key: normalized domain
- TTL: 1 hour (3600000 ms)
- Automatic cleanup of expired entries
- Cache statistics tracking

#### Error Handling
- API key validation
- Invalid domain handling
- API timeout management
- Rate limiting from Brand.dev
- Empty result handling
- Network error handling

#### Configuration Requirements
- API key from environment: `BRAND_DEV_API_KEY`
- Brand.dev npm package equivalent in Python
- HTTP client configuration
- Cache size limits (optional)

---

### 1.3 Background Removal Service

**Purpose**: Dedicated endpoint for removing backgrounds from images using advanced AI models, optimized for product photography, profile pictures, and design assets.

#### Key Features
- High-quality background removal
- Transparent PNG output
- Optional cropping to bounding box
- Synchronous and asynchronous processing
- S3 storage with CDN delivery
- Cost: 2 credits per operation

#### Core Methods to Implement

**1. `removeBackground(userId, imageUrl, options)`**
- Main background removal method
- Parameters:
  - `userId`: User identifier
  - `imageUrl`: Source image URL (HTTP/HTTPS)
  - `sync_mode`: Use synchronous Fal processing (default: false)
  - `crop_to_bbox`: Crop to foreground object bounding box (default: false)
  - `waitForCompletion`: Wait for processing (default: true)
  - `timeoutMs`: Max wait time (default: 60000)

- **Returns**:
```typescript
{
  success: boolean,
  assetId: string,
  imageUrl?: string,  // S3 URL with transparent background
  creditsUsed: 2,
  creditsRemaining: number,
  model: "fal-ai/imageutils/rembg",
  metadata?: {
    width: number,
    height: number,
    format: "png",
    hasAlpha: true
  },
  error?: string
}
```

**2. `uploadResultToS3(imageData, userId, originalFilename)`**
- Upload processed image to S3
- Generate proper S3 key: `generated/nobg/{userId}/{timestamp}_{filename}.png`
- Return public or presigned URL

**3. `validateImageUrl(url)`**
- Validate HTTP/HTTPS URL format
- Check if URL is accessible
- Verify image format

#### Processing Flow
1. Validate user credits (require 2 credits minimum)
2. Validate image URL
3. Deduct credits atomically
4. Submit to Fal AI rembg model
5. Poll for completion (if waitForCompletion=true)
6. Download result
7. Upload to S3
8. Update asset record in database
9. Return result with URLs
10. Refund credits if any step fails

#### Model Configuration
- Model: `fal-ai/imageutils/rembg`
- Input: `image_url`, `sync_mode`, `crop_to_bbox`
- Output: PNG with alpha channel
- Processing time: Usually < 30 seconds

#### Use Cases
- Product photography (transparent backgrounds)
- Profile pictures (isolated portraits)
- Design assets (object extraction)
- E-commerce (consistent backgrounds)

---

## 2. Project Management Services

### 2.1 Projects Service

**Purpose**: Core project lifecycle management service acting as the main orchestrator for AI-powered development projects. Handles project CRUD operations, state management, and coordination with sandbox sessions.

#### Key Features
- Project lifecycle management (create, list, get, pause, resume, delete)
- Integration with sandbox service
- Project metadata management
- Conversation history tracking
- Project state management
- Multi-user project support
- Ownership enforcement

#### Core Methods to Implement

**1. `createProject(userId, projectData)`**
- Create new project with sandbox session
- Parameters:
  - `userId`: User identifier
  - `name`: Project name
  - `description`: Project description (optional)
  - `type`: Project type (default: "GAME")

- **Process Flow**:
  1. Generate unique project ID (`proj_` + 12 random chars)
  2. Create sandbox session via SandboxService
  3. Create project record in database
  4. Initialize metadata (frontend_url, backend_url, empty conversation history)
  5. Set status to ACTIVE, sandbox_state to RUNNING

- **Returns**:
```typescript
{
  project_id: string,
  name: string,
  description?: string,
  type: string,
  status: "ACTIVE" | "PAUSED" | "DELETED",
  sandbox_state: "RUNNING" | "PAUSED" | "STOPPED",
  sandbox_id: string,
  frontend_url?: string,
  backend_url?: string,
  created_at: Date,
  last_active: Date,
  metadata: {...}
}
```

**2. `getProjects(userId, limit, offset)`**
- List all user projects with pagination
- Sort by last_active descending
- Include project statistics
- Returns project count and array

**3. `getProject(userId, projectId)`**
- Get single project details
- Verify ownership
- Include all metadata
- Throw 404 if not found

**4. `resumeProject(userId, projectId)`**
- Resume a paused project
- Restart sandbox session
- Update URLs if changed
- Update last_active timestamp
- Set status to ACTIVE, sandbox_state to RUNNING

**5. `pauseProject(userId, projectId)`**
- Pause active project to save resources
- Pause sandbox via SandboxService
- Update status to PAUSED, sandbox_state to PAUSED
- Preserve all project data and conversation history

**6. `deleteProject(userId, projectId)`**
- Soft delete project
- Stop sandbox session
- Set status to DELETED
- Preserve data for recovery (optional hard delete later)
- Clean up associated assets (optional)

**7. `updateLastActive(projectId)`**
- Update last_active timestamp
- Called on every interaction (chat, file upload, etc.)

**8. `getProjectState(userId, projectId)`**
- Get current project state
- Include sandbox status
- Include file counts, asset counts
- Include conversation history summary

#### Project Metadata Structure
```typescript
{
  frontend_url?: string,
  backend_url?: string,
  documents?: Array<{
    asset_id: string,
    filename: string,
    s3_url: string,
    file_type: string,
    language?: string,
    is_code_file: boolean,
    summary?: string,
    total_chunks?: number,
    token_count?: number,
    rag_processed: boolean,
    added_at: string
  }>,
  images?: Array<{
    asset_id: string,
    filename: string,
    s3_url: string,
    image_url: string,
    analysis?: string,
    rag_processed: boolean,
    added_at: string
  }>,
  conversationHistory?: Array<{
    role: 'user' | 'assistant' | 'system' | 'tool',
    content: string,
    timestamp: Date
  }>
}
```

#### Error Handling
- Project not found (404)
- Unauthorized access (403)
- Resource limit exceeded (429) - too many active sandboxes
- Sandbox creation failure
- Database transaction failures
- Invalid project state transitions

#### Database Schema Requirements
- `Project` table with fields:
  - id (string, primary key)
  - userId (string, foreign key)
  - name (string)
  - description (text, nullable)
  - type (enum: GAME, WEB_APP, etc.)
  - status (enum: ACTIVE, PAUSED, DELETED)
  - active_sandbox_id (string, nullable)
  - sandbox_state (enum: RUNNING, PAUSED, STOPPED)
  - metadata (JSON)
  - created_at (timestamp)
  - last_active (timestamp)
  - updated_at (timestamp)

---

### 2.2 Sandbox Service

**Purpose**: Manages E2B sandbox sessions for interactive development environments. Handles sandbox lifecycle, URL management, and coordination with Python AI backend.

#### Key Features
- Sandbox session creation and management
- Session resume and pause functionality
- URL tracking (frontend and backend URLs)
- Integration with E2B API
- Resource limit enforcement
- Automatic cleanup

#### Core Methods to Implement

**1. `createSandboxSession(userId, projectId)`**
- Create new E2B sandbox session
- Call Python API: `POST /api/sandbox/session`
- Request body: `{ user_id, project_id }`
- Timeout: 60 seconds
- Returns: `{ sandbox_id, frontend_url, backend_url }`

**2. `resumeSandboxSession(userId, projectId, sandboxId?)`**
- Resume paused sandbox or restore from snapshot
- Call Python API: `POST /api/sandbox/resume`
- Request body: `{ user_id, project_id, sandbox_id? }`
- Timeout: 45 seconds
- Returns updated URLs (may change)

**3. `pauseSandboxSession(userId, projectId)`**
- Pause running sandbox to save resources
- Call Python API: `POST /api/sandbox/pause`
- Request body: `{ user_id, project_id }`
- Returns: `{ success: boolean, message: string }`

**4. `deleteSandboxSession(userId, projectId)`**
- Permanently delete sandbox
- Call Python API: `POST /api/sandbox/delete`
- Clean up all sandbox resources
- Cannot be recovered after deletion

**5. `getSandboxUrls(userId, projectId)`**
- Get current sandbox URLs
- Fetch from project metadata or query Python API
- Returns: `{ frontend_url, backend_url, sandbox_id }`

**6. `getSandboxStatus(userId, projectId)`**
- Query sandbox status from E2B
- Returns running/paused/stopped state
- Include resource usage (optional)

#### Python API Integration Requirements

The Python backend should expose these endpoints:
- `POST /api/sandbox/session` - Create sandbox
- `POST /api/sandbox/resume` - Resume sandbox
- `POST /api/sandbox/pause` - Pause sandbox
- `POST /api/sandbox/delete` - Delete sandbox
- `GET /api/sandbox/status` - Get status (optional)

#### Error Handling
- Resource limit exceeded (429) - max sandboxes per user
- Sandbox creation timeout
- E2B API failures
- Invalid sandbox state transitions
- Network errors to Python backend
- Database sync failures

#### Configuration Requirements
- Python API URL (from environment)
- E2B API credentials (handled by Python backend)
- Sandbox resource limits
- Timeout configurations

---

### 2.3 Chat Service

**Purpose**: Real-time streaming chat interface with AI agents. Handles Server-Sent Events (SSE) streaming, conversation history, and integration with Python AI backend.

#### Key Features
- SSE streaming for real-time responses
- Multi-model support (GPT-4, Claude, Gemini, etc.)
- Document context injection (RAG)
- Image context for vision models
- Conversation history management
- Configurable temperature, timeout, max tokens
- Multi-provider support (OpenAI, Anthropic, Google, OpenRouter)

#### Core Methods to Implement

**1. `streamChat(projectId, userId, model, modelProvider, message, documentContext, imageUrls, options)`**
- Main chat streaming method
- Call Python API: `POST /chat`
- Returns SSE stream (Axios response)

- **Parameters**:
  - `projectId`: Project/thread ID for conversation context
  - `userId`: User ID for memory namespace
  - `model`: AI model name (e.g., "x-ai/grok-4-fast", "gpt-4-turbo")
  - `modelProvider`: Provider enum (openai, anthropic, google_genai, openrouter)
  - `message`: User message text
  - `documentContext`: Array of document summaries for RAG
  - `imageUrls`: Array of image URLs for vision models
  - `options`:
    - `temperature`: 0.0-1.0 (default: 0.5)
    - `timeout`: Processing timeout in seconds (default: 300)
    - `maxTokens`: Max response tokens (default: 16000)

- **Request Payload to Python**:
```typescript
{
  message: string,
  project_id: string,
  user_id: string,
  model: string,
  model_provider: string,
  streaming: true,
  temperature: number,
  timeout: number,
  max_tokens: number,
  document_context: array,
  image_urls: array
}
```

- **SSE Stream Events**:
  - `agent_start`: Agent begins processing
  - `agent_thinking`: Reasoning/planning phase
  - `tool_start`: Tool execution begins
  - `tool_complete`: Tool execution finished
  - `agent_complete`: Final response ready
  - `error`: Error occurred

**2. `getHistory(projectId, userId, limit)`**
- Retrieve conversation history
- Call Python API: `POST /projects/history`
- Request: `{ project_id, limit }`
- Returns: `{ project_id, count, history: [...] }`
- Timeout: 30 seconds

**3. `updateLastActive(projectId)`**
- Update project last_active timestamp
- Called before every chat request

#### Document Context Structure
```typescript
Array<{
  asset_id: string,
  filename: string,
  file_type: string,
  summary?: string,
  content_chunks?: string[],
  token_count?: number
}>
```

#### Image Context Requirements
- Support image URLs for vision models
- Multiple images per request
- URL validation
- Image preprocessing (optional)

#### Streaming Response Handling
- Accept: text/event-stream header
- Proper SSE parsing
- Connection timeout: 30 minutes
- Chunked transfer encoding
- Error recovery and reconnection

#### Error Handling
- Python backend connection failures
- Stream interruption
- Timeout handling
- Invalid model/provider combinations
- Token limit exceeded
- Rate limiting

#### Python API Requirements
The Python backend must implement:
- `POST /chat` - Streaming chat endpoint
- `POST /projects/history` - History retrieval
- SSE event formatting
- Proper error propagation via SSE

---

### 2.4 Assets Service

**Purpose**: Comprehensive asset management for project files including documents, images, and generic files. Handles upload, processing, RAG integration, and S3 storage.

#### Key Features
- Multi-type file support (documents, images, generic files)
- S3 upload and storage
- Document processing and chunking
- Image analysis and vision processing
- RAG (Retrieval Augmented Generation) integration
- Batch document upload
- Asset deletion and cleanup
- Presigned URL generation for Python access

#### Core Methods to Implement

**1. `uploadDocument(projectId, userId, file)`**
- Upload and process document files (PDF, TXT, MD, code files, etc.)
- Flow:
  1. Upload file to S3: `projects/{projectId}/documents/{timestamp}-{filename}`
  2. Generate presigned URL for Python (2 hours expiration)
  3. Send to Python API for processing
  4. Store metadata in database
  5. Add to project metadata

- **Python API Call**: `POST /api/documents/process`
- **Request**:
```typescript
{
  document: {
    filename: string,
    filetype: string,
    metadata: {
      file_size: number,
      uploaded_at: string
    },
    public_url: string  // Presigned URL for Python to access
  },
  project_id: string,
  user_id: string
}
```

- **Response from Python**:
```typescript
{
  success: boolean,
  asset_id: string,
  filename: string,
  file_type: string,
  language?: string,
  is_code_file: boolean,
  summary?: string,
  total_chunks?: number,
  token_count?: number,
  rag_processed: boolean,
  message?: string
}
```

- **Returns**:
```typescript
{
  success: boolean,
  asset_id: string,
  filename: string,
  s3_url: string,
  file_type: string,
  language?: string,
  is_code_file: boolean,
  summary?: string,
  total_chunks?: number,
  token_count?: number,
  rag_processed: boolean,
  added_at: string
}
```

**2. `uploadImage(projectId, userId, file)`**
- Upload and analyze image files
- Flow:
  1. Upload to S3: `projects/{projectId}/images/{timestamp}-{filename}`
  2. Generate presigned URL for Python
  3. Send to Python API for vision analysis
  4. Store metadata in database
  5. Add to project metadata

- **Python API Call**: `POST /api/images/analyze`
- **Request**:
```typescript
{
  image: {
    filename: string,
    metadata: {
      file_size: number,
      uploaded_at: string
    },
    public_url: string  // Presigned URL
  },
  project_id: string,
  user_id: string
}
```

- **Response from Python**:
```typescript
{
  success: boolean,
  asset_id: string,
  filename: string,
  analysis?: string,
  rag_processed: boolean,
  message?: string
}
```

**3. `uploadGenericFile(projectId, userId, file)`**
- Upload files without processing
- Direct S3 storage
- Minimal metadata
- Returns S3 URL and asset ID

**4. `batchUploadDocuments(projectId, userId, files)`**
- Upload multiple documents in parallel
- Concurrent S3 uploads
- Parallel Python API calls
- Aggregate results
- Return success/failure per file

- **Returns**:
```typescript
{
  project_id: string,
  total: number,
  successful: number,
  failed: number,
  results: Array<{
    filename: string,
    success: boolean,
    asset_id?: string,
    error?: string,
    ...documentMetadata
  }>
}
```

**5. `getProjectAssets(projectId, userId)`**
- List all project assets
- Filter by type (documents, images, files)
- Include metadata and URLs
- Sort by added date

- **Returns**:
```typescript
{
  project_id: string,
  total_count: number,
  documents: Array<DocumentMetadata>,
  images: Array<ImageMetadata>,
  files: Array<FileMetadata>
}
```

**6. `deleteAsset(projectId, userId, assetId)`**
- Remove asset from project
- Delete from S3 (optional, can keep for recovery)
- Remove from project metadata
- Clean up database records
- Notify Python backend for RAG cleanup

**7. `generateAssetId()`**
- Generate unique asset ID
- Format: `asset_` + 12 random alphanumeric chars

#### S3 Storage Requirements
- Upload to DigitalOcean Spaces
- Organization:
  - Documents: `projects/{projectId}/documents/`
  - Images: `projects/{projectId}/images/`
  - Generic: `projects/{projectId}/files/`
- Generate presigned URLs for Python backend access (2-hour expiration)
- Store permanent public URLs in database
- Support ACL configuration

#### Document Processing Flow (Python Backend)
1. Download file from presigned URL
2. Extract text content
3. Detect file type and language
4. Classify as code/non-code
5. Generate summary (AI)
6. Split into chunks for RAG
7. Count tokens
8. Store in vector database
9. Mark as rag_processed
10. Return metadata

#### Image Processing Flow (Python Backend)
1. Download image from presigned URL
2. Run vision model analysis
3. Extract image description
4. Detect objects/text (optional)
5. Store in vector database for RAG
6. Mark as rag_processed
7. Return metadata

#### Error Handling
- File size limits (validate before upload)
- Invalid file types
- S3 upload failures
- Python API timeouts
- Processing failures (partial success handling)
- Database sync errors

#### Configuration Requirements
- Max file size per upload
- Supported file types
- Python API URL
- S3 credentials and bucket info
- Presigned URL expiration times

---

### 2.5 Files Service

**Purpose**: Manages project file structure, provides file system tree views, and handles file CRUD operations within sandbox environments.

#### Key Features
- File structure management (flat and tree views)
- File content retrieval
- File metadata tracking
- Tree structure building from flat paths
- Sorting and filtering
- Deletion tracking (soft delete)

#### Core Methods to Implement

**1. `getProjectFiles(projectId, userId)`**
- Get all files in flat structure
- Verify project ownership
- Filter out deleted files
- Sort by file path alphabetically

- **Returns**:
```typescript
{
  project_id: string,
  file_count: number,
  files: Array<{
    id: string,
    file_path: string,
    content: string,
    size_bytes: number,
    mime_type: string,
    created_by_tool: string,
    created_at: string,
    updated_at: string
  }>,
  updated_at: string
}
```

**2. `getProjectFilesWithTree(projectId, userId)`**
- Get files with hierarchical tree structure
- Build tree from flat file paths
- Include both tree and flat list
- Useful for file explorer UI

- **Returns**:
```typescript
{
  project_id: string,
  file_count: number,
  tree: Array<FileTreeNode>,
  files: Array<ProjectFileDto>,
  updated_at: string
}
```

**FileTreeNode Structure**:
```typescript
{
  name: string,
  type: 'file' | 'folder',
  path: string,
  children?: Array<FileTreeNode>,
  size_bytes?: number,  // for files only
  file_id?: string,  // for files only
  updated_at?: string  // for files only
}
```

**3. `buildFileTree(files)`**
- Convert flat file paths to tree structure
- Handle nested directories
- Sort: folders first, then alphabetically
- Recursive tree building

**4. `sortTree(treeNodes)`**
- Sort tree nodes: folders before files
- Alphabetical within each type
- Recursive sorting for nested folders

**5. `getLatestTimestamp(files)`**
- Find most recent updated_at from file list
- Used for cache invalidation

#### File Path Handling
- Support Unix-style paths: `/src/components/Button.tsx`
- Handle nested directories
- Preserve path separators
- Case-sensitive paths

#### Database Schema Requirements
- `ProjectFile` table:
  - id (string, primary key)
  - project_id (string, foreign key)
  - file_path (string, unique within project)
  - content (text)
  - size_bytes (integer)
  - mime_type (string)
  - created_by_tool (string) - which tool created this file
  - is_deleted (boolean, default false)
  - created_at (timestamp)
  - updated_at (timestamp)

#### Use Cases
- File explorer UI in frontend
- Code navigation
- File search and filtering
- Project structure visualization
- Export/download preparation

---

### 2.6 Download Service

**Purpose**: Project export and ZIP file creation service. Creates downloadable archives of project files with intelligent filtering and S3 storage.

#### Key Features
- ZIP file creation from project files
- Configurable source paths and exclusions
- Default exclusion patterns (node_modules, .git, etc.)
- S3 upload with presigned download URLs
- ZIP file listing and management
- Automatic cleanup of old files
- Custom ZIP naming

#### Core Methods to Implement

**1. `createDownload(projectId, userId, options)`**
- Create ZIP archive of project files
- Call Python API: `POST /api/projects/download`
- Upload ZIP to S3
- Generate download URL

- **Parameters**:
  - `projectId`: Project identifier
  - `userId`: User identifier
  - `sourcePath`: Path to zip (default: project root)
  - `zipName`: Custom ZIP filename (optional)
  - `excludePatterns`: Array of glob patterns to exclude
  - `useDefaults`: Use default exclusions (default: true)
  - `urlExpiration`: URL expiration in seconds (optional)

- **Request to Python**:
```typescript
{
  user_id: string,
  project_id: string,
  source_path: string | null,
  zip_name: string | null,
  exclude_patterns: string[] | null,
  use_defaults: boolean,
  url_expiration: number | null
}
```

- **Response**:
```typescript
{
  success: boolean,
  project_id: string,
  zip_name: string,
  zip_path: string,  // Local path on Python server
  zip_size_bytes: number,
  download_url: string,  // Presigned S3 URL
  url_expiration: number,  // Seconds
  created_at: string,
  expires_at: string,
  message?: string
}
```

- **Timeout**: 3 minutes (180000ms)

**2. `listZips(projectId, userId)`**
- List all ZIP files for a project
- Call Python API: `POST /api/projects/list-zips`
- Include file metadata and download URLs

- **Request**:
```typescript
{
  user_id: string,
  project_id: string
}
```

- **Response**:
```typescript
{
  project_id: string,
  zip_count: number,
  zips: Array<{
    zip_name: string,
    zip_path: string,
    zip_size_bytes: number,
    download_url: string,
    created_at: string,
    expires_at: string
  }>,
  message?: string
}
```

**3. `cleanupOldZips(projectId, userId, daysOld?)`**
- Delete ZIP files older than specified days
- Call Python API: `POST /api/projects/cleanup-zips`
- Free up storage space

- **Request**:
```typescript
{
  user_id: string,
  project_id: string,
  days_old?: number  // Default: 7
}
```

- **Response**:
```typescript
{
  project_id: string,
  deleted_count: number,
  freed_bytes: number,
  message: string
}
```

#### Default Exclusion Patterns
```
node_modules/
.git/
.next/
.cache/
dist/
build/
__pycache__/
*.pyc
.DS_Store
.env
.env.local
```

#### ZIP Creation Flow (Python Backend)
1. Validate project access
2. Determine source path
3. Apply exclusion patterns
4. Create ZIP archive in memory or temp directory
5. Upload ZIP to S3
6. Generate presigned download URL
7. Store ZIP metadata
8. Return download info

#### S3 Storage Organization
```
downloads/
└── {project_id}/
    └── {zip_name}_{timestamp}.zip
```

#### Error Handling
- Invalid source path
- Permission errors
- ZIP creation failures
- S3 upload failures
- Insufficient disk space
- Timeout on large projects
- Network errors

#### Configuration Requirements
- Python API URL
- S3 bucket and credentials
- Max ZIP size limit
- Default URL expiration time
- Cleanup schedule configuration

---

## 3. User & Credits Management

### 3.1 Users Service

**Purpose**: User authentication, authorization, and profile management using wallet-based authentication with support for multiple blockchain networks.

#### Key Features
- Wallet-based authentication (Sign-In with Ethereum)
- Multi-chain support (Ethereum, Polygon, Arbitrum, Optimism, Base, BSC, Avalanche)
- JWT token generation and validation
- Refresh token mechanism
- Challenge-response authentication (nonce-based)
- User profile management
- ENS (Ethereum Name Service) support
- Cached message validation

#### Core Methods to Implement

**1. `getMessage(walletAddress)`**
- Generate authentication challenge message
- Create unique nonce for security
- Cache message with TTL (5 minutes)
- Format: Sign-in message with wallet address and nonce

- **Returns**:
```typescript
{
  nonce: number,
  msg: string
}
```

- **Message Format**:
```
Welcome to Generative-World! Click to sign in.

This request will not trigger a blockchain transaction or cost any gas fees, it is just a way to verify your wallet address.

Wallet address: {walletAddress}
Nonce: {nonce}
```

**2. `login(walletAddress, signature, chainId)`**
- Verify signature against cached message
- Validate signature using viem library
- Create or update user record
- Generate access and refresh tokens
- Initialize user credits if new user

- **Parameters**:
  - `walletAddress`: Ethereum address (0x...)
  - `signature`: Signed message from wallet
  - `chainId`: Blockchain network ID

- **Process Flow**:
  1. Validate wallet address format
  2. Get cached message for address
  3. Verify signature using appropriate chain
  4. Create user if doesn't exist
  5. Initialize Credits record (1000 free credits)
  6. Generate JWT access token (1 hour)
  7. Generate refresh token (7 days)
  8. Cache tokens
  9. Return tokens and user info

- **Returns**:
```typescript
{
  accessToken: string,
  refreshToken: string,
  user: {
    id: string,
    walletAddress: string,
    email?: string,
    username?: string,
    currentPlan: 'FREE' | 'TOP_UP' | 'SUBSCRIPTION',
    credits: number
  }
}
```

**3. `refreshToken(refreshToken)`**
- Validate refresh token
- Generate new access token
- Extend refresh token expiry
- Return new token pair

**4. `verifyToken(accessToken)`**
- Validate JWT token
- Check expiration
- Extract user ID
- Return decoded token payload

**5. `updateUserDetails(userId, updates)`**
- Update user profile information
- Fields: email, username, avatar
- Validate uniqueness constraints
- Return updated user

**6. `getUserProfile(userId)`**
- Get user profile with credits
- Include subscription info
- Return plan details

**7. `verifySignature(message, signature, walletAddress, chainId)`**
- Use viem library for signature verification
- Support multiple chains
- Return boolean verification result

#### Supported Blockchain Networks
- **Mainnet**: Ethereum (1), Polygon (137), Arbitrum (42161), Optimism (10), Base (8453), BSC (56), Avalanche (43114)
- **Testnet**: Sepolia (11155111), Polygon Amoy (80002), Arbitrum Sepolia (421614), Optimism Sepolia (11155420), Base Sepolia (84532), BSC Testnet (97), Avalanche Fuji (43113)

#### JWT Token Structure
- **Access Token**:
  - Expiration: 1 hour
  - Payload: `{ userId, walletAddress, iat, exp }`
  - Algorithm: HS256 (or jose library default)

- **Refresh Token**:
  - Expiration: 7 days
  - Payload: `{ userId, type: 'refresh', iat, exp }`
  - Algorithm: HS256

#### Security Considerations
- Nonce uniqueness and expiration
- Signature replay attack prevention
- Token rotation on refresh
- Secure token storage in cache
- Rate limiting on login attempts
- Wallet address normalization (lowercase)

#### Error Handling
- Invalid wallet address format
- Signature verification failure
- Expired nonce/message
- Unsupported chain ID
- Token expiration
- Invalid refresh token
- Database errors

#### Configuration Requirements
- JWT secret key (from environment)
- Redis/cache configuration
- Supported chain configurations
- Token expiration times
- Initial free credits amount

---

### 3.2 Credits Management Service (Game Gen Credit Service)

**Purpose**: Comprehensive credit management system for tracking, deducting, and billing usage across sandbox sessions and AI model calls with integration to OpenMeter for billing.

#### Key Features
- Atomic credit transactions (prevent race conditions)
- Multi-plan support (FREE, TOP_UP, SUBSCRIPTION)
- Sandbox usage billing
- AI model usage billing (token-based)
- OpenMeter integration for billing insights
- Credit refunds on failures
- Usage tracking and analytics
- Automatic plan upgrades/downgrades

#### Core Methods to Implement

**1. `processSandboxCharge(params)`**
- Deduct credits for sandbox session usage
- Send usage data to OpenMeter
- Track sandbox duration and cost

- **Parameters**:
```typescript
{
  userId: string,
  projectId: string,
  sandboxId: string,
  creditsToDeduct: number
}
```

- **Process Flow**:
  1. Validate user and credits
  2. Deduct credits atomically
  3. Log transaction
  4. Send to OpenMeter
  5. Return success/failure

**2. `processAIModelCharge(params)`**
- Deduct credits for AI model token usage
- Calculate cost based on input/output tokens
- Support different model pricing

- **Parameters**:
```typescript
{
  userId: string,
  projectId: string,
  modelName: string,
  inputTokens: number,
  outputTokens: number,
  totalTokens: number
}
```

- **Process Flow**:
  1. Look up model pricing
  2. Calculate credit cost
  3. Deduct credits atomically
  4. Log transaction
  5. Send to OpenMeter
  6. Return cost info

**3. `deductCredits(userId, credits, chargeType, identifier)`**
- Unified atomic credit deduction
- Support all plan types
- Transaction-safe to prevent race conditions

- **Process Flow**:
  1. Start database transaction
  2. Lock user Credits record
  3. Validate sufficient credits
  4. Deduct based on plan type:
     - FREE: Deduct from free_credits
     - TOP_UP: Deduct from top_up_balance
     - SUBSCRIPTION: Deduct from subscription_credits
  5. Create transaction log
  6. Commit transaction
  7. Handle rollback on error

**4. `refundCredits(userId, credits, reason, originalTransactionId)`**
- Refund credits on failures
- Add back to appropriate plan
- Log refund transaction
- Link to original transaction

**5. `checkSufficientCredits(userId, requiredCredits)`**
- Pre-check before operations
- Return boolean and current balance
- No deduction

**6. `getCreditsBalance(userId)`**
- Get current credit balance
- Include breakdown by plan
- Return total available credits

**7. `addCredits(userId, credits, source, metadata)`**
- Add credits (purchases, promotions, admin grants)
- Update appropriate plan balance
- Log transaction
- Send to OpenMeter

**8. `getUserUsageStats(userId, timeRange)`**
- Get usage statistics
- Breakdown by type (sandbox, AI model)
- Time-based aggregation
- Export for billing

#### Credit Plan Types

**FREE Plan**:
- Initial credits: 1000
- No refills
- Depletes to 0
- Can upgrade to TOP_UP or SUBSCRIPTION

**TOP_UP Plan**:
- Pay-as-you-go
- Credits purchased in bulk
- Never expires
- Depletes based on usage

**SUBSCRIPTION Plan**:
- Monthly credit allocation
- Resets each billing cycle
- Unused credits may roll over (configurable)
- Can exceed with overage charges

#### Transaction Logging
```typescript
{
  id: string,
  user_id: string,
  transaction_type: 'DEDUCTION' | 'REFUND' | 'PURCHASE' | 'GRANT',
  amount: number,
  balance_after: number,
  charge_type: 'SANDBOX' | 'AI_MODEL' | 'IMAGE_GEN' | 'OTHER',
  identifier: string,  // sandbox_id, model_name, etc.
  metadata: JSON,
  created_at: timestamp
}
```

#### OpenMeter Integration

**Purpose**: Send usage events for billing and analytics

**Event Structure**:
```typescript
{
  userId: string,
  projectId: string,
  identifier: string,  // sandbox_id or model_name
  credits: number,
  type: 'game-gen-sandbox' | 'ai-model' | 'image-generation',
  timestamp: ISO_timestamp,
  metadata?: {
    modelName?: string,
    inputTokens?: number,
    outputTokens?: number,
    duration?: number
  }
}
```

**Methods**:
- `sendToOpenMeter(event)` - Send usage event
- `getOpenMeterStats(userId, timeRange)` - Retrieve analytics

#### Model Pricing Configuration
```typescript
{
  'gpt-4-turbo': {
    input_per_1k: 0.01,  // $0.01 per 1K input tokens
    output_per_1k: 0.03,  // $0.03 per 1K output tokens
    credit_conversion: 100  // $1 = 100 credits
  },
  'claude-3-opus': { ... },
  'grok-4-fast': { ... }
}
```

#### Error Handling
- Insufficient credits (prevent operation)
- Race conditions (transaction isolation)
- Database deadlocks (retry logic)
- OpenMeter API failures (queue for retry)
- Invalid plan type
- Negative credits

#### Configuration Requirements
- Model pricing table
- Credit to currency conversion rates
- OpenMeter API endpoint and key
- Plan limits and quotas
- Refund policies

---

### 3.3 Coupons Service

**Purpose**: Promotional coupon system for credit distribution, user acquisition, and marketing campaigns with admin-only management.

#### Key Features
- Admin-only coupon creation and management
- Unique coupon codes
- Credit amount configuration
- Redemption tracking
- Active/inactive status
- One-time or multi-use coupons (configurable)
- Bulk coupon generation
- Usage analytics

#### Core Methods to Implement

**1. `createCoupon(userId, couponData)`**
- Admin creates new coupon code
- Verify admin privileges
- Validate uniqueness
- Set credit amount and limits

- **Parameters**:
```typescript
{
  code: string,  // e.g., "WELCOME2024"
  creditAmount: number,
  maxRedemptions?: number,  // null = unlimited
  expiresAt?: Date,
  isActive?: boolean  // default: true
}
```

- **Admin Validation**:
  - Check user wallet address matches ADMIN_WALLET_ADDRESS environment variable
  - Throw UnauthorizedException if not admin

- **Returns**:
```typescript
{
  id: string,
  code: string,
  creditAmount: number,
  isActive: boolean,
  redemptionCount: number,
  maxRedemptions?: number,
  expiresAt?: Date,
  createdAt: Date,
  updatedAt: Date
}
```

**2. `generateCoupons(userId, generateData)`**
- Bulk generate multiple coupons
- Auto-generate unique codes or use prefix pattern
- Same credit amount for all

- **Parameters**:
```typescript
{
  count: number,  // How many coupons to generate
  codePrefix?: string,  // e.g., "PROMO_" → PROMO_ABC123
  creditAmount: number,
  maxRedemptionsEach?: number,
  expiresAt?: Date
}
```

- **Returns**:
```typescript
{
  generated: number,
  coupons: Array<{
    id: string,
    code: string,
    creditAmount: number
  }>
}
```

**3. `redeemCoupon(userId, couponCode)`**
- User redeems coupon for credits
- Validate coupon exists and is active
- Check expiration
- Check redemption limits
- Add credits to user
- Log redemption

- **Parameters**:
  - `userId`: User redeeming
  - `couponCode`: Coupon code (case-insensitive)

- **Process Flow**:
  1. Find coupon by code (case-insensitive)
  2. Validate coupon is active
  3. Check not expired
  4. Check redemption limits
  5. Check user hasn't already redeemed (one per user)
  6. Add credits to user account
  7. Create redemption record
  8. Increment redemption count
  9. Return success with new credit balance

- **Returns**:
```typescript
{
  success: boolean,
  message: string,
  creditsAdded: number,
  newBalance: number,
  couponCode: string,
  redeemedAt: Date
}
```

**4. `updateCoupon(userId, couponId, updates)`**
- Admin updates coupon details
- Can activate/deactivate
- Can change credit amount (affects future redemptions)
- Can change limits

**5. `getCoupon(userId, couponCode)`**
- Get coupon details
- Include redemption stats
- Admin or public info based on caller

**6. `listCoupons(userId, filters)`**
- Admin lists all coupons
- Filter by: active status, expiration, redemption status
- Include statistics (total redemptions, credits distributed)

**7. `deleteCoupon(userId, couponId)`**
- Admin soft-delete coupon
- Mark as inactive
- Preserve redemption history

**8. `getCouponStats(userId, couponId)`**
- Admin view coupon analytics
- Total redemptions
- Unique users
- Credits distributed
- Redemption timeline

#### Coupon Code Generation
- Random alphanumeric codes
- Configurable length (default: 8-12 characters)
- Optional prefix/suffix
- Uniqueness validation
- Avoid confusing characters (0/O, 1/I/l)

#### Redemption Rules
- One redemption per user per coupon (configurable)
- Active status check
- Expiration date check
- Max redemptions limit check
- User must be authenticated

#### Database Schema Requirements

**Coupon Table**:
```typescript
{
  id: string,
  code: string (unique, indexed),
  creditAmount: number,
  isActive: boolean,
  maxRedemptions: number (nullable),
  expiresAt: Date (nullable),
  createdAt: Date,
  updatedAt: Date,
  createdBy: string (admin user_id)
}
```

**CouponRedemption Table**:
```typescript
{
  id: string,
  couponId: string (foreign key),
  userId: string (foreign key),
  creditsGranted: number,
  redeemedAt: Date
}
```

#### Error Handling
- Unauthorized access (non-admin)
- Duplicate coupon code
- Invalid coupon code
- Expired coupon
- Max redemptions reached
- Already redeemed by user
- Inactive coupon
- Invalid credit amount (must be positive)

#### Configuration Requirements
- Admin wallet address (environment variable)
- Default coupon code length
- Max credits per coupon limit (optional)
- Coupon expiration defaults

---

## 4. Infrastructure Services

### 4.1 S3/Storage Service

**Purpose**: Comprehensive DigitalOcean Spaces (S3-compatible) storage service for file uploads, downloads, presigned URL generation, and asset management.

#### Key Features
- S3-compatible storage (AWS SDK)
- Presigned URL generation (upload and download)
- Public and private file support
- File metadata management
- Batch operations
- File copying and moving
- Existence checks and validation
- CDN integration

#### Core Methods to Implement

**1. `generatePresignedUrl(fileKey, expiresIn)`**
- Generate presigned URL for downloading private files
- Max expiration: 3 hours (10800 seconds)
- Validate file key format

- **Parameters**:
  - `fileKey`: S3 object key/path
  - `expiresIn`: URL expiration in seconds (default: 3600)

- **Returns**: Presigned URL string

**2. `getSecurePresignedUrl(fileName, userId, expiresIn)`**
- Generate presigned URL for uploading files
- Auto-generate S3 key: `uploads/{userId}/{timestamp}-{sanitized_filename}`
- Return both URL and key

- **Returns**:
```typescript
{
  url: string,  // Presigned upload URL
  key: string   // S3 object key
}
```

**3. `getAdvancedPresignedUrl(fileKey, userId, options)`**
- Advanced presigned URL with custom options
- Support ACL, server-side encryption, metadata, cache control
- Require specific headers in upload

- **Options**:
```typescript
{
  expiresIn?: number,
  acl?: 'public-read' | 'private',
  contentType?: string,
  serverSideEncryption?: string,
  metadata?: Record<string, string>,
  cacheControl?: string
}
```

**4. `uploadFileToS3(key, fileBuffer, mimeType, acl?)`**
- Direct file upload to S3
- Set ACL (public-read or private)
- Set content type

- **Parameters**:
  - `key`: S3 object key
  - `fileBuffer`: File data (Buffer)
  - `mimeType`: MIME type
  - `acl`: Access control (optional)

**5. `getPublicUrl(fileKey)`**
- Get direct public URL for public files
- Format: `https://{bucket}.{region}.digitaloceanspaces.com/{key}`

**6. `getExternalApiUrl(fileKey, expiresIn)`**
- Generate presigned URL for external API access
- Longer expiration (up to 2 hours default)
- Used for Python backend to access files

**7. `downloadFileFromUrl(url)`**
- Download file from URL to buffer
- Support HTTP/HTTPS
- Timeout handling
- Return file buffer

**8. `copyFile(sourceKey, destinationKey, acl?)`**
- Copy S3 object to new location
- Preserve or change ACL
- Useful for file organization

**9. `moveFile(sourceKey, destinationKey, acl?)`**
- Move S3 object (copy + delete source)
- Atomic operation with rollback

**10. `deleteFile(fileKey)`**
- Delete S3 object
- Permanent deletion

**11. `listFiles(prefix, maxKeys?)`**
- List objects with common prefix
- Pagination support
- Return file metadata

**12. `fileExists(fileKey)`**
- Check if file exists in S3
- HEAD request (no download)
- Return boolean

**13. `getFileMetadata(fileKey)`**
- Get file metadata (size, content-type, last-modified)
- HEAD request

**14. `sanitizeFileName(fileName)`**
- Remove special characters
- Replace spaces with underscores
- Preserve file extension
- Make URL-safe

**15. `validateFileKey(fileKey)`**
- Validate S3 key format
- Check length (max 1024)
- Check forbidden characters (null bytes, newlines)

#### S3 Configuration
- **Endpoint**: DigitalOcean Spaces endpoint
- **Region**: Spaces region (e.g., nyc3, sfo2)
- **Bucket**: Bucket name
- **Credentials**: Access key ID and secret access key
- **ACL Support**: public-read, private
- **Encryption**: Optional server-side encryption

#### File Organization Patterns

**User Uploads**:
```
uploads/{userId}/{timestamp}-{filename}
```

**Generated Images**:
```
generated/images/{userId}/{timestamp}_{prompt}.png
```

**Project Documents**:
```
projects/{projectId}/documents/{timestamp}-{filename}
```

**Project Images**:
```
projects/{projectId}/images/{timestamp}-{filename}
```

**Downloads/ZIPs**:
```
downloads/{projectId}/{zipname}_{timestamp}.zip
```

#### Error Handling
- Invalid file key format
- File not found (404)
- Access denied (403)
- S3 SDK errors
- Network errors
- Upload failures
- Validation errors

#### Security Considerations
- Validate all file keys
- Sanitize file names
- Cap presigned URL expiration
- Use private ACL by default
- Validate file sizes before upload
- Check MIME types

#### Configuration Requirements
- DigitalOcean Spaces credentials (environment):
  - `DO_SPACES_ENDPOINT`
  - `DO_SPACES_REGION`
  - `DO_SPACES_KEY`
  - `DO_SPACES_SECRET`
  - `DO_SPACES_BUCKET`
- Max file size limits
- Default expiration times
- Allowed MIME types (optional)

---

### 4.2 E2B Webhook Service

**Purpose**: Manages E2B (sandbox environment) webhook lifecycle for automatic billing based on sandbox usage events. Registers, validates, and processes webhooks from E2B API.

#### Key Features
- Automatic webhook registration on startup
- Signature verification for security
- Sandbox lifecycle event processing
- Usage tracking and billing integration
- Webhook health monitoring
- Event deduplication
- Retry logic for failed processing

#### Core Methods to Implement

**1. `onModuleInit()`**
- Called when service starts
- Register webhooks if not already registered
- Validate E2B API key
- Set up event listeners

**2. `registerWebhooksIfNeeded()`**
- Check existing webhooks via E2B API
- Register new webhooks if missing
- Events to register:
  - `sandbox.start`
  - `sandbox.stop`
  - `sandbox.timeout`
  - `sandbox.error`

- **E2B API Call**: `GET /webhooks`
- **Webhook Registration**: `POST /webhooks`

- **Webhook Payload**:
```typescript
{
  name: "NestJS Backend Webhook",
  url: "{SELF_DOMAIN}/api/webhooks/e2b",
  events: [
    "sandbox.start",
    "sandbox.stop",
    "sandbox.timeout",
    "sandbox.error"
  ],
  enabled: true
}
```

**3. `verifyWebhookSignature(payload, signature)`**
- Verify E2B webhook signature using HMAC
- Use webhook secret from environment
- Prevent unauthorized webhook calls

- **Algorithm**:
```javascript
const expectedSignature = crypto
  .createHmac('sha256', WEBHOOK_SECRET)
  .update(JSON.stringify(payload))
  .digest('hex');
return signature === expectedSignature;
```

**4. `handleWebhook(payload, signature)`**
- Main webhook handler
- Verify signature first
- Route to appropriate event handler
- Log all events
- Return 200 OK quickly (process async)

**5. `processSandboxStart(event)`**
- Handle sandbox.start event
- Extract user_id, project_id from metadata
- Record start time in database
- Initialize usage tracking

- **Event Data**:
```typescript
{
  sandboxId: string,
  sandboxExecutionId: string,
  timestamp: string,
  event_data: {
    sandbox_metadata: {
      user_id: string,
      project_id: string,
      created_at: string
    }
  }
}
```

**6. `processSandboxStop(event)`**
- Handle sandbox.stop event
- Calculate session duration
- Calculate credits to charge
- Call GameGenCreditService.processSandboxCharge()
- Log billing event

- **Billing Calculation**:
```javascript
duration_minutes = (stop_time - start_time) / 60000;
credits = Math.ceil(duration_minutes * CREDITS_PER_MINUTE);
```

**7. `processSandboxTimeout(event)`**
- Handle sandbox timeout
- Similar to stop but may have different billing
- Log timeout reason
- Charge for actual usage

**8. `processSandboxError(event)`**
- Handle sandbox errors
- Log error details
- Decide on billing (charge for usage until error or not)
- May trigger refunds

**9. `listWebhooks()`**
- List all registered webhooks
- Call E2B API: `GET /webhooks`
- Return webhook configurations

**10. `updateWebhook(webhookId, updates)`**
- Update webhook configuration
- Enable/disable webhooks
- Change events
- Call E2B API: `PUT /webhooks/{id}`

**11. `deleteWebhook(webhookId)`**
- Delete webhook
- Call E2B API: `DELETE /webhooks/{id}`

**12. `getWebhookHealth()`**
- Check webhook status
- Verify connectivity
- Return health metrics

#### E2B API Integration

**Base URL**: `https://api.e2b.app`

**Authentication**: 
- Header: `Authorization: Bearer {E2B_API_KEY}`

**Endpoints**:
- `GET /webhooks` - List webhooks
- `POST /webhooks` - Create webhook
- `GET /webhooks/{id}` - Get webhook
- `PUT /webhooks/{id}` - Update webhook
- `DELETE /webhooks/{id}` - Delete webhook

#### Webhook Event Types

**sandbox.start**:
- Fired when sandbox starts
- Contains sandbox ID and metadata
- Start billing timer

**sandbox.stop**:
- Fired when sandbox stops normally
- Calculate duration and bill

**sandbox.timeout**:
- Fired when sandbox times out
- May have different billing rules

**sandbox.error**:
- Fired on sandbox errors
- Decide on billing based on error type

#### Usage Tracking Database Schema

**SandboxSession Table**:
```typescript
{
  id: string,
  sandbox_id: string,
  user_id: string,
  project_id: string,
  started_at: DateTime,
  stopped_at: DateTime (nullable),
  duration_minutes: number (nullable),
  credits_charged: number (nullable),
  status: 'RUNNING' | 'STOPPED' | 'TIMEOUT' | 'ERROR',
  error_message: string (nullable)
}
```

#### Billing Configuration
```typescript
{
  CREDITS_PER_MINUTE: 0.5,  // Example: 0.5 credits per minute
  MIN_BILLABLE_TIME: 1,     // Minimum 1 minute billing
  ROUND_UP: true            // Always round up to next minute
}
```

#### Error Handling
- Invalid webhook signature (reject with 401)
- Missing event data (log and skip)
- Billing failures (retry with exponential backoff)
- E2B API errors (log and alert)
- Duplicate events (deduplicate by event ID)

#### Event Deduplication
- Track processed event IDs in cache
- TTL: 24 hours
- Prevent double billing

#### Configuration Requirements
- Environment variables:
  - `E2B_API_KEY`: E2B API key
  - `SELF_DOMAIN`: Public domain for webhook callbacks
  - `E2B_WEBHOOK_SECRET`: Secret for signature verification
  - `E2B_CREDITS_PER_MINUTE`: Billing rate
- HTTP client with retry logic
- Async event queue for processing

#### Security Best Practices
- Always verify webhook signatures
- Use HTTPS for webhook URL
- Keep webhook secret secure
- Rate limit webhook endpoint
- Log all webhook events for audit
- Monitor for suspicious patterns

---

## 5. Implementation Priorities

### Phase 1: Core Infrastructure (Week 1-2)
**Priority: CRITICAL**

1. **S3/Storage Service** (4.1)
   - Essential for all file operations
   - Needed by almost every other service
   - Implement first: basic upload, download, presigned URLs

2. **Users Service** (3.1)
   - Authentication foundation
   - Required for all protected endpoints
   - JWT token generation and validation

3. **Credits Management Service** (3.2)
   - Core billing mechanism
   - Needed for all paid features
   - Implement atomic transactions carefully

### Phase 2: Generation Services (Week 2-3)
**Priority: HIGH**

4. **Image/Text Generation Service** (1.1)
   - Main value proposition
   - Includes credit integration
   - Complex but high-impact

5. **Brand Data Service** (1.2)
   - Relatively simple
   - Independent service
   - Good for parallel development

6. **Background Removal Service** (1.3)
   - Similar to generation service
   - Can reuse patterns from 1.1

### Phase 3: Project Management Core (Week 3-4)
**Priority: HIGH**

7. **Projects Service** (2.1)
   - Central orchestrator
   - Foundation for other project services
   - Implement before dependent services

8. **Sandbox Service** (2.2)
   - Required for projects
   - E2B integration
   - Critical for development environments

9. **Chat Service** (2.3)
   - Main user interaction
   - SSE streaming implementation
   - Depends on Projects service

### Phase 4: Asset & File Management (Week 4-5)
**Priority: MEDIUM-HIGH**

10. **Assets Service** (2.4)
    - Document and image management
    - RAG integration
    - Batch upload support

11. **Files Service** (2.5)
    - File structure management
    - Tree building
    - Relatively simple

12. **Download Service** (2.6)
    - ZIP creation
    - Export functionality
    - Lower complexity

### Phase 5: Additional Features (Week 5-6)
**Priority: MEDIUM**

13. **Coupons Service** (3.3)
    - Marketing and promotions
    - Admin-only features
    - Can be added later

14. **E2B Webhook Service** (4.2)
    - Automated billing
    - Background processing
    - Important for production but not MVP

---

## Implementation Guidelines

### API Design Patterns

**Consistent Response Format**:
```typescript
{
  success: boolean,
  data?: any,
  error?: {
    code: string,
    message: string,
    details?: any
  },
  metadata?: {
    timestamp: string,
    requestId: string
  }
}
```

**Error Handling**:
- Use appropriate HTTP status codes
- Provide detailed error messages
- Include error codes for client handling
- Log all errors server-side

**Authentication**:
- Bearer token in Authorization header
- Validate on every protected endpoint
- Extract userId from token
- Verify ownership for resource access

**Pagination**:
```typescript
{
  items: Array<any>,
  total: number,
  limit: number,
  offset: number,
  hasMore: boolean
}
```

### Database Considerations

**Transaction Safety**:
- Use transactions for credit operations
- Implement row-level locking where needed
- Handle deadlocks with retry logic

**Indexing**:
- Index foreign keys
- Index frequently queried fields
- Composite indexes for complex queries

**Data Integrity**:
- Foreign key constraints
- NOT NULL constraints where appropriate
- Unique constraints on codes/identifiers

### Testing Requirements

**Unit Tests**:
- Test each method independently
- Mock external dependencies
- Cover edge cases and errors

**Integration Tests**:
- Test API endpoints end-to-end
- Test authentication flow
- Test database operations

**Load Tests**:
- Test concurrent credit operations
- Test file upload limits
- Test SSE streaming under load

### Security Checklist

- [ ] Input validation on all endpoints
- [ ] SQL injection prevention (use parameterized queries)
- [ ] XSS prevention (sanitize outputs)
- [ ] Rate limiting on expensive operations
- [ ] File type validation on uploads
- [ ] File size limits enforcement
- [ ] Presigned URL expiration
- [ ] Webhook signature verification
- [ ] Token expiration and rotation
- [ ] Secrets in environment variables (never in code)

### Performance Optimization

**Caching Strategy**:
- Cache frequently accessed data (brand data, user profiles)
- Use Redis for distributed cache
- Implement cache invalidation

**Async Processing**:
- Use background jobs for heavy tasks (ZIP creation, batch uploads)
- Implement job queues (Bull, Celery, etc.)
- Progress tracking for long operations

**Database Queries**:
- Use query optimization
- Avoid N+1 queries
- Use database connection pooling

---

## Python Backend Architecture Recommendations

### FastAPI Framework
- Use FastAPI for REST API
- Automatic OpenAPI documentation
- Pydantic for request/response validation
- Built-in async support

### Key Libraries
- **httpx**: Async HTTP client for external APIs
- **boto3/aioboto3**: AWS SDK for S3
- **sqlalchemy**: ORM for database
- **alembic**: Database migrations
- **redis-py**: Redis client
- **python-jose**: JWT handling
- **cryptography**: Signature verification
- **fal-client**: Fal.ai Python SDK
- **brand-dev** (if available): Brand.dev integration

### Project Structure
```
python_backend/
├── app/
│   ├── api/
│   │   ├── routes/
│   │   │   ├── generation.py
│   │   │   ├── projects.py
│   │   │   ├── assets.py
│   │   │   └── ...
│   ├── services/
│   │   ├── generation_service.py
│   │   ├── brand_service.py
│   │   ├── s3_service.py
│   │   └── ...
│   ├── models/
│   │   ├── user.py
│   │   ├── project.py
│   │   └── ...
│   ├── schemas/
│   │   ├── generation.py
│   │   ├── project.py
│   │   └── ...
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   └── database.py
│   └── main.py
├── tests/
├── alembic/
├── requirements.txt
└── .env.example
```

### Environment Variables Template
```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/dbname

# Redis
REDIS_URL=redis://localhost:6379

# S3/DigitalOcean Spaces
DO_SPACES_ENDPOINT=https://nyc3.digitaloceanspaces.com
DO_SPACES_REGION=nyc3
DO_SPACES_KEY=your_key
DO_SPACES_SECRET=your_secret
DO_SPACES_BUCKET=your_bucket

# External APIs
FAL_API_KEY=your_fal_key
BRAND_DEV_API_KEY=your_brand_key
OPENAI_API_KEY=your_openai_key

# E2B
E2B_API_KEY=your_e2b_key
E2B_WEBHOOK_SECRET=your_webhook_secret

# Authentication
JWT_SECRET=your_jwt_secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Admin
ADMIN_WALLET_ADDRESS=0xYourAdminWallet

# OpenMeter (optional)
OPENMETER_API_KEY=your_openmeter_key
OPENMETER_ENDPOINT=https://openmeter.io

# Python Backend (for NestJS to call)
PYTHON_API_URL=http://localhost:8000

# Self Domain (for webhooks)
SELF_DOMAIN=https://your-domain.com
```

---

## Conclusion

This specification provides a comprehensive blueprint for implementing production-ready tools in your Python backend. Each service is documented with:

- Clear purpose and features
- Detailed method specifications
- Request/response formats
- Error handling requirements
- Database schema needs
- Configuration requirements
- Implementation priorities

**Next Steps**:
1. Review and validate this specification
2. Set up Python backend infrastructure
3. Implement Phase 1 services first (S3, Users, Credits)
4. Test thoroughly before moving to next phase
5. Deploy incrementally with monitoring
6. Gather feedback and iterate

**Success Criteria**:
- All endpoints match NestJS functionality
- Credit system is transaction-safe
- File uploads/downloads work reliably
- Authentication is secure
- Performance meets requirements (< 2s for most operations)
- Error handling is comprehensive
- Documentation is complete

Good luck with your Python backend development! 🚀
