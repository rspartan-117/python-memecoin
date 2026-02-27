# NestJS Integration Guide - Python Landing Page Generation Backend

## Overview

This guide provides comprehensive instructions for integrating the Python Landing Page Generation Backend with your NestJS application, following a clear separation of concerns architecture.

**Base URL**: `http://localhost:8000` (configure as needed)

---

## 📋 Table of Contents

1. [Architecture & Separation of Concerns](#architecture--separation-of-concerns)
2. [Database Schema Overview](#database-schema-overview)
3. [Integration Flows](#integration-flows)
4. [API Endpoints Reference](#api-endpoints-reference)
5. [NestJS Implementation Guide](#nestjs-implementation-guide)
6. [Error Handling](#error-handling)
7. [Best Practices](#best-practices)

---

## 🏗️ Architecture & Separation of Concerns

### Responsibility Matrix

| Component | Responsibility | Technologies |
|-----------|---------------|--------------|
| **NestJS Backend** | • All CRUD database operations<br>• User/Project management<br>• Asset upload to S3<br>• Business logic & orchestration<br>• API gateway for frontend | PostgreSQL, Prisma, S3, NestJS |
| **Python Backend** | • Agent/AI processing & generation<br>• Sandbox creation & management<br>• Agent memory & conversation history<br>• Document/image processing (RAG)<br>• File operations in sandbox | LangGraph, E2B, MongoDB, FastAPI |

### Key Principles

1. **Database Operations**: NestJS handles ALL database writes/updates
2. **Agent Logic**: Python manages agent state, memory, and conversation history
3. **Sandbox Management**: Python creates/manages sandboxes; NestJS tracks state in DB
4. **Asset Processing**: NestJS uploads to S3 → Python processes → NestJS stores metadata

### Important Note on Current Implementation

**⚠️ Current State**: The Python sandbox manager currently updates the database for sandbox state synchronization. However, **NestJS should also update the database** from API responses to maintain proper separation and ensure data consistency. In future iterations, Python-side DB updates may be removed for cleaner separation.

---

## 📊 Database Schema Overview

### Project Model (Shared Schema)

The `Project` table is the central entity managed by NestJS:

```typescript
// Prisma Schema (NestJS side)
model Project {
  id                String       @id
  userId            String       @map("userId")
  name              String
  description       String?
  type              ProjectType  @default(GAME)
  
  // Sandbox tracking (updated by NestJS from Python responses)
  active_sandbox_id String?      @map("active_sandbox_id")
  sandbox_state     SandboxState @default(NONE)
  
  // Session tracking
  status            SessionStatus @default(ACTIVE)
  created_at        DateTime     @default(now())
  updated_at        DateTime     @updatedAt
  last_active       DateTime     @default(now())
  ended_at          DateTime?
  
  // Metadata (stores asset processing results)
  metadata          Json?        // { documents: [], images: [] }
  
  user              User         @relation(fields: [userId], references: [id], onDelete: Cascade)
}

enum SandboxState {
  NONE    // No sandbox created yet
  RUNNING // Sandbox is active
  PAUSED  // Sandbox is paused (manual or auto)
  KILLED  // Sandbox expired (>30 days)
}

enum SessionStatus {
  ACTIVE
  PAUSED
  ENDED
}

enum ProjectType {
  GAME
  FULLSTACK
  LANDING_PAGE
  CODE_ANALYSIS
}
```

### Metadata Structure

```typescript
interface ProjectMetadata {
  documents?: Array<{
    asset_id: string;
    filename: string;
    s3_url: string;
    file_type: string;
    language?: string; // For code files
    is_code_file: boolean;
    summary: string;
    total_chunks: number;
    token_count: number;
    rag_processed: boolean;
    added_at: string;
  }>;
  
  images?: Array<{
    asset_id: string;
    filename: string;
    s3_url: string;
    image_url: string;
    analysis: string;
    rag_processed: boolean;
    added_at: string;
  }>;
}
```

---

## 🔄 Integration Flows

### Flow 1: New Session (Completely New Project)

**When**: User creates a brand new project

```
┌─────────────┐
│   NestJS    │
└──────┬──────┘
       │
       │ 1. Create Project in DB
       │    - id, userId, name, type
       │    - sandbox_state = NONE
       │    - status = ACTIVE
       ▼
┌──────────────────┐
│  PostgreSQL DB   │
│  Project Table   │
└──────────────────┘
       │
       │ 2. Call Python: POST /api/sandbox/session
       │    Body: { user_id, project_id }
       ▼
┌─────────────┐
│   Python    │
│   Backend   │
└──────┬──────┘
       │
       │ 3. Python creates/gets sandbox
       │    - Returns: sandbox_id, frontend_url, backend_url
       │    - (Python may update DB internally for sync)
       ▼
┌─────────────┐
│   NestJS    │
└──────┬──────┘
       │
       │ 4. Update Project in DB
       │    - active_sandbox_id = response.sandbox_id
       │    - sandbox_state = RUNNING
       │    - last_active = now()
       ▼
┌──────────────────┐
│  PostgreSQL DB   │
└──────────────────┘
       │
       │ 5. Call Python: POST /chat
       │    Body: { message, project_id, user_id, ... }
       ▼
┌─────────────┐
│   Python    │
│   Backend   │ (Streams SSE events)
└─────────────┘
```

**NestJS Code Example**:

```typescript
// projects.service.ts
async createProject(userId: string, projectData: CreateProjectDto) {
  // 1. Create project in DB
  const project = await this.prisma.project.create({
    data: {
      id: generateId(), // Or use UUID
      userId,
      name: projectData.name,
      type: projectData.type || 'FULLSTACK',
      sandbox_state: 'NONE',
      status: 'ACTIVE',
    },
  });

  // 2. Create/get sandbox
  const sandboxResponse = await this.pythonService.createSandboxSession({
    user_id: userId,
    project_id: project.id,
  });

  // 3. Update project with sandbox info
  await this.prisma.project.update({
    where: { id: project.id },
    data: {
      active_sandbox_id: sandboxResponse.sandbox_id,
      sandbox_state: 'RUNNING',
      last_active: new Date(),
      // Optionally store URLs in metadata or separate fields
    },
  });

  // 4. Return project with sandbox info
  return {
    ...project,
    sandbox_id: sandboxResponse.sandbox_id,
    frontend_url: sandboxResponse.frontend_url,
    backend_url: sandboxResponse.backend_url,
  };
}
```

---

### Flow 2: Existing Session (Resume/Continue)

**When**: User returns to an existing project

```
┌─────────────┐
│   NestJS    │
└──────┬──────┘
       │
       │ 1. Get Project from DB
       │    - Check sandbox_state (RUNNING/PAUSED/KILLED)
       ▼
┌──────────────────┐
│  PostgreSQL DB   │
└──────┬───────────┘
       │
       │ 2. Call Python: POST /api/sandbox/session
       │    Body: { user_id, project_id }
       │    (Python handles reconnection/resume automatically)
       ▼
┌─────────────┐
│   Python    │
│   Backend   │
└──────┬──────┘
       │
       │ 3. Python returns sandbox info
       │    - May reconnect to existing sandbox
       │    - May create new if expired
       │    - Returns: sandbox_id, frontend_url, backend_url
       ▼
┌─────────────┐
│   NestJS    │
└──────┬──────┘
       │
       │ 4. Update Project in DB
       │    - active_sandbox_id = response.sandbox_id (if changed)
       │    - sandbox_state = RUNNING
       │    - last_active = now()
       ▼
┌──────────────────┐
│  PostgreSQL DB   │
└──────────────────┘
       │
       │ 5. Continue with chat requests
       │    POST /chat (multiple times as needed)
       ▼
┌─────────────┐
│   Python    │
│   Backend   │
└─────────────┘
```

**NestJS Code Example**:

```typescript
// projects.service.ts
async resumeProject(userId: string, projectId: string) {
  // 1. Get project from DB
  const project = await this.prisma.project.findUnique({
    where: { id: projectId, userId },
  });

  if (!project) {
    throw new NotFoundException('Project not found');
  }

  // 2. Get/Resume sandbox session
  const sandboxResponse = await this.pythonService.createSandboxSession({
    user_id: userId,
    project_id: projectId,
  });

  // 3. Update project state
  await this.prisma.project.update({
    where: { id: projectId },
    data: {
      active_sandbox_id: sandboxResponse.sandbox_id,
      sandbox_state: 'RUNNING',
      last_active: new Date(),
      status: 'ACTIVE', // Update session status if needed
    },
  });

  return {
    project,
    sandbox_id: sandboxResponse.sandbox_id,
    frontend_url: sandboxResponse.frontend_url,
    backend_url: sandboxResponse.backend_url,
  };
}
```

---

### Flow 3: Document Processing → Chat

**When**: User uploads a document/image before chatting

```
┌─────────────┐
│   NestJS    │
└──────┬──────┘
       │
       │ 1. Upload file to S3
       │    - Get S3 URL
       ▼
┌─────────────┐
│     S3      │
└──────┬──────┘
       │
       │ 2. Call Python: POST /assets/process-document
       │    Body: { s3_url, filename, session_id, user_id }
       ▼
┌─────────────┐
│   Python    │
│   Backend   │
└──────┬──────┘
       │
       │ 3. Python processes document
       │    - Downloads from S3
       │    - Generates summary
       │    - Creates chunks & embeddings (stored in MongoDB)
       │    - Returns: DocumentProcessingResult
       ▼
┌─────────────┐
│   NestJS    │
└──────┬──────┘
       │
       │ 4. Store metadata in Project.metadata.documents[]
       │    await prisma.project.update({
       │      where: { id: projectId },
       │      data: {
       │        metadata: {
       │          documents: [...existing, processingResult]
       │        }
       │      }
       │    })
       ▼
┌──────────────────┐
│  PostgreSQL DB   │
└──────────────────┘
       │
       │ 5. Later: Call Python: POST /chat
       │    Body: {
       │      message,
       │      project_id,
       │      document_context: project.metadata.documents.map(...)
       │    }
       ▼
┌─────────────┐
│   Python    │
│   Backend   │ (Uses document context for RAG)
└─────────────┘
```

**NestJS Code Example**:

```typescript
// assets.service.ts
async processDocument(
  userId: string,
  projectId: string,
  file: Express.Multer.File
) {
  // 1. Upload to S3 (your existing S3 service)
  const s3Url = await this.s3Service.uploadFile(file);

  // 2. Call Python to process
  const processingResult = await this.pythonService.processDocument({
    s3_url: s3Url,
    filename: file.originalname,
    session_id: projectId, // project_id == session_id
    user_id: userId,
    content_type: file.mimetype,
  });

  if (!processingResult.success) {
    throw new BadRequestException(processingResult.message);
  }

  // 3. Get current project metadata
  const project = await this.prisma.project.findUnique({
    where: { id: projectId },
    select: { metadata: true },
  });

  const currentMetadata = (project?.metadata as ProjectMetadata) || {};
  const currentDocuments = currentMetadata.documents || [];

  // 4. Add document to metadata
  const documentEntry = {
    asset_id: processingResult.asset_id,
    filename: processingResult.filename,
    s3_url: processingResult.s3_url,
    file_type: processingResult.file_type,
    language: processingResult.language,
    is_code_file: processingResult.is_code_file,
    summary: processingResult.summary,
    total_chunks: processingResult.total_chunks,
    token_count: processingResult.token_count,
    rag_processed: processingResult.rag_processed,
    added_at: new Date().toISOString(),
  };

  await this.prisma.project.update({
    where: { id: projectId },
    data: {
      metadata: {
        ...currentMetadata,
        documents: [...currentDocuments, documentEntry],
      },
    },
  });

  return processingResult;
}

// Later, when sending chat request
async sendChatMessage(userId: string, projectId: string, message: string) {
  // Get project with metadata
  const project = await this.prisma.project.findUnique({
    where: { id: projectId, userId },
  });

  if (!project) {
    throw new NotFoundException('Project not found');
  }

  const metadata = (project.metadata as ProjectMetadata) || {};

  // Extract document context for Python
  const documentContext = (metadata.documents || []).map((doc) => ({
    filename: doc.filename,
    type: doc.file_type,
    summary: doc.summary,
  }));

  // Extract image URLs for vision models
  const imageUrls = (metadata.images || []).map((img) => img.s3_url);

  // Call Python chat endpoint
  return this.pythonService.chat({
    message,
    project_id: projectId,
    user_id: userId,
    document_context: documentContext,
    image_urls: imageUrls.length > 0 ? imageUrls : undefined,
  });
}
```

---

## 📡 API Endpoints Reference

### Sandbox Management Endpoints

#### POST `/api/sandbox/session`

**Purpose**: Get or create sandbox session (PRIMARY endpoint)

**Request**:
```typescript
{
  user_id: string;
  project_id: string;
}
```

**Response**:
```typescript
{
  success: boolean;
  sandbox_id: string;
  user_id: string;
  project_id: string;
  frontend_url: string | null; // Port 3000
  backend_url: string | null;  // Port 8000
  message: string;
}
```

**NestJS Action**: Update `Project.active_sandbox_id` and `Project.sandbox_state = 'RUNNING'`

---

#### POST `/api/sandbox/pause`

**Purpose**: Pause sandbox session

**Request**:
```typescript
{
  user_id: string;      // Required
  project_id: string;   // Required
  timeout?: number;     // Optional: New timeout in seconds
}
```

**Response**:
```typescript
{
  success: boolean;
  sandbox_id: string;
  paused: boolean;
  timeout?: number;
  message: string;
}
```

**NestJS Action**: Update `Project.sandbox_state = 'PAUSED'`

---

#### POST `/api/sandbox/resume`

**Purpose**: Resume sandbox session (alias for `/session`)

**Request**:
```typescript
{
  user_id: string;
  project_id: string;
}
```

**Response**:
```typescript
{
  success: boolean;
  sandbox_id: string;
  resumed: boolean;
  message: string;
}
```

**NestJS Action**: Update `Project.sandbox_state = 'RUNNING'` and `Project.last_active`

---

### Agent/Chat Endpoints

#### POST `/chat`

**Purpose**: Stream chat with AI agent (Server-Sent Events)

**Request**:
```typescript
{
  message: string;
  project_id: string;              // Required: Used as thread_id/session_id
  user_id: string;                 // Default: "default-user"
  model?: string;                  // Default: "x-ai/grok-4-fast"
  model_provider?: string;         // "openai" | "anthropic" | "google_genai" | "openrouter"
  streaming?: boolean;             // Default: true
  temperature?: number;            // Default: 0.5
  timeout?: number;                // Default: 300
  max_tokens?: number;             // Default: 1000
  image_urls?: string[];           // For vision models
  document_context?: Array<{       // From Project.metadata.documents
    filename: string;
    type: string;
    summary: string;
  }>;
}
```

**Response**: `text/event-stream` (SSE)

**Event Types**: `agent_start`, `agent_thinking`, `tool_start`, `tool_complete`, `agent_complete`, `error`

**NestJS Action**: Stream events to frontend (no DB update needed - Python handles agent state)

---

#### GET `/projects/{project_id}/history`

**Purpose**: Get conversation history (Python-managed)

**Response**: Returns conversation messages from Python's checkpointer

**NestJS Action**: Read-only, display to user

---

#### GET `/projects/{project_id}/state`

**Purpose**: Get current agent state (Python-managed)

**Response**: Returns agent state from Python's checkpointer

**NestJS Action**: Read-only, display progress to user

---

### Asset Processing Endpoints

#### POST `/assets/process-document`

**Purpose**: Process document file from S3

**Request**:
```typescript
{
  s3_url: string;           // Required
  filename: string;         // Required
  session_id: string;       // Required (project_id)
  user_id: string;          // Required
  content_type?: string;    // Optional
}
```

**Response**:
```typescript
{
  success: boolean;
  asset_id: string;
  filename: string;
  s3_url: string;
  file_type: string;
  language?: string;
  is_code_file: boolean;
  summary: string;
  total_chunks: number;
  token_count: number;
  rag_processed: boolean;
  error?: string;
  message: string;
}
```

**NestJS Action**: Store result in `Project.metadata.documents[]`

---

#### POST `/assets/process-image`

**Purpose**: Process image file from S3

**Request**:
```typescript
{
  s3_url: string;           // Required
  filename: string;         // Required
  session_id: string;       // Required (project_id)
  content_type?: string;    // Optional
}
```

**Response**:
```typescript
{
  success: boolean;
  asset_id: string;
  filename: string;
  s3_url: string;
  image_url: string;
  analysis: string;
  rag_processed: boolean;
  error?: string;
  message: string;
}
```

**NestJS Action**: Store result in `Project.metadata.images[]`

---

#### POST `/assets/process-asset`

**Purpose**: Process asset (document or image) - auto-routes based on file type

**Request**: Same as `process-document` or `process-image` depending on file type

**Response**: Either `DocumentProcessingResult` or `ImageProcessingResult`

---

## 💻 NestJS Implementation Guide

### 1. Service Setup

```typescript
// python-api.service.ts
import { Injectable, HttpService } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Observable } from 'rxjs';

@Injectable()
export class PythonApiService {
  private readonly baseUrl: string;

  constructor(
    private readonly httpService: HttpService,
    private readonly configService: ConfigService
  ) {
    this.baseUrl = this.configService.get<string>(
      'PYTHON_API_URL',
      'http://localhost:8000'
    );
  }

  // Sandbox Management
  async createSandboxSession(data: { user_id: string; project_id: string }) {
    const response = await this.httpService
      .post(`${this.baseUrl}/api/sandbox/session`, data)
      .toPromise();
    return response.data;
  }

  async pauseSandbox(data: { user_id: string; project_id: string; timeout?: number }) {
    const response = await this.httpService
      .post(`${this.baseUrl}/api/sandbox/pause`, data)
      .toPromise();
    return response.data;
  }

  async resumeSandbox(data: { user_id: string; project_id: string }) {
    const response = await this.httpService
      .post(`${this.baseUrl}/api/sandbox/resume`, data)
      .toPromise();
    return response.data;
  }

  // Chat (returns Observable for SSE streaming)
  chat(data: {
    message: string;
    project_id: string;
    user_id: string;
    document_context?: Array<{ filename: string; type: string; summary: string }>;
    image_urls?: string[];
    [key: string]: any;
  }): Observable<any> {
    return this.httpService.post(`${this.baseUrl}/chat`, data, {
      responseType: 'stream',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
    });
  }

  // Asset Processing
  async processDocument(data: {
    s3_url: string;
    filename: string;
    session_id: string;
    user_id: string;
    content_type?: string;
  }) {
    const response = await this.httpService
      .post(`${this.baseUrl}/assets/process-document`, data)
      .toPromise();
    return response.data;
  }

  async processImage(data: {
    s3_url: string;
    filename: string;
    session_id: string;
    content_type?: string;
  }) {
    const response = await this.httpService
      .post(`${this.baseUrl}/assets/process-image`, data)
      .toPromise();
    return response.data;
  }

  async processAsset(data: {
    s3_url: string;
    filename: string;
    session_id: string;
    user_id: string;
    content_type?: string;
  }) {
    const response = await this.httpService
      .post(`${this.baseUrl}/assets/process-asset`, data)
      .toPromise();
    return response.data;
  }

  // Agent State (read-only)
  async getProjectHistory(projectId: string) {
    const response = await this.httpService
      .get(`${this.baseUrl}/projects/${projectId}/history`)
      .toPromise();
    return response.data;
  }

  async getProjectState(projectId: string) {
    const response = await this.httpService
      .get(`${this.baseUrl}/projects/${projectId}/state`)
      .toPromise();
    return response.data;
  }
}
```

### 2. Project Service with DB Updates

```typescript
// projects.service.ts
import { Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from './prisma.service';
import { PythonApiService } from './python-api.service';

@Injectable()
export class ProjectsService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly pythonApi: PythonApiService
  ) {}

  /**
   * Create new project and initialize sandbox
   */
  async createProject(userId: string, data: CreateProjectDto) {
    // 1. Create project in DB
    const project = await this.prisma.project.create({
      data: {
        id: this.generateProjectId(), // Your ID generation logic
        userId,
        name: data.name,
        description: data.description,
        type: data.type || 'FULLSTACK',
        sandbox_state: 'NONE',
        status: 'ACTIVE',
      },
    });

    try {
      // 2. Create sandbox via Python
      const sandboxResponse = await this.pythonApi.createSandboxSession({
        user_id: userId,
        project_id: project.id,
      });

      // 3. Update project with sandbox info (NestJS handles DB update)
      const updatedProject = await this.prisma.project.update({
        where: { id: project.id },
        data: {
          active_sandbox_id: sandboxResponse.sandbox_id,
          sandbox_state: 'RUNNING',
          last_active: new Date(),
        },
      });

      return {
        ...updatedProject,
        frontend_url: sandboxResponse.frontend_url,
        backend_url: sandboxResponse.backend_url,
      };
    } catch (error) {
      // If sandbox creation fails, project still exists but without sandbox
      // You might want to update sandbox_state to indicate error
      throw error;
    }
  }

  /**
   * Resume existing project session
   */
  async resumeProject(userId: string, projectId: string) {
    // 1. Get project
    const project = await this.prisma.project.findUnique({
      where: { id: projectId, userId },
    });

    if (!project) {
      throw new NotFoundException('Project not found');
    }

    // 2. Get/resume sandbox session
    const sandboxResponse = await this.pythonApi.createSandboxSession({
      user_id: userId,
      project_id: projectId,
    });

    // 3. Update project state (NestJS handles DB update)
    const updatedProject = await this.prisma.project.update({
      where: { id: projectId },
      data: {
        active_sandbox_id: sandboxResponse.sandbox_id,
        sandbox_state: 'RUNNING',
        last_active: new Date(),
        status: 'ACTIVE',
      },
    });

    return {
      ...updatedProject,
      frontend_url: sandboxResponse.frontend_url,
      backend_url: sandboxResponse.backend_url,
    };
  }

  /**
   * Pause project sandbox
   */
  async pauseProject(userId: string, projectId: string, timeout?: number) {
    const project = await this.prisma.project.findUnique({
      where: { id: projectId, userId },
    });

    if (!project) {
      throw new NotFoundException('Project not found');
    }

    // Pause via Python
    const pauseResponse = await this.pythonApi.pauseSandbox({
      user_id: userId,
      project_id: projectId,
      timeout,
    });

    // Update DB state (NestJS handles DB update)
    const updatedProject = await this.prisma.project.update({
      where: { id: projectId },
      data: {
        sandbox_state: 'PAUSED',
        last_active: new Date(),
      },
    });

    return updatedProject;
  }

  /**
   * Send chat message to agent
   */
  async sendChatMessage(
    userId: string,
    projectId: string,
    message: string,
    options?: ChatOptions
  ) {
    // Get project with metadata
    const project = await this.prisma.project.findUnique({
      where: { id: projectId, userId },
    });

    if (!project) {
      throw new NotFoundException('Project not found');
    }

    // Extract document context and image URLs from metadata
    const metadata = (project.metadata as ProjectMetadata) || {};
    const documentContext = (metadata.documents || [])
      .filter((doc) => doc.rag_processed)
      .map((doc) => ({
        filename: doc.filename,
        type: doc.file_type,
        summary: doc.summary,
      }));

    const imageUrls = (metadata.images || [])
      .filter((img) => img.rag_processed)
      .map((img) => img.s3_url);

    // Update last_active
    await this.prisma.project.update({
      where: { id: projectId },
      data: { last_active: new Date() },
    });

    // Call Python chat endpoint (returns Observable for SSE)
    return this.pythonApi.chat({
      message,
      project_id: projectId,
      user_id: userId,
      document_context: documentContext.length > 0 ? documentContext : undefined,
      image_urls: imageUrls.length > 0 ? imageUrls : undefined,
      ...options,
    });
  }

  private generateProjectId(): string {
    // Your ID generation logic (UUID, nanoid, etc.)
    return `project_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }
}
```

### 3. Assets Service

```typescript
// assets.service.ts
import { Injectable, BadRequestException } from '@nestjs/common';
import { PrismaService } from './prisma.service';
import { PythonApiService } from './python-api.service';
import { S3Service } from './s3.service'; // Your S3 service

@Injectable()
export class AssetsService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly pythonApi: PythonApiService,
    private readonly s3Service: S3Service
  ) {}

  /**
   * Upload and process document
   */
  async uploadDocument(
    userId: string,
    projectId: string,
    file: Express.Multer.File
  ) {
    // 1. Upload to S3 (your existing S3 service)
    const s3Url = await this.s3Service.uploadFile(file, {
      folder: `projects/${projectId}/documents`,
    });

    // 2. Process via Python
    const result = await this.pythonApi.processDocument({
      s3_url: s3Url,
      filename: file.originalname,
      session_id: projectId,
      user_id: userId,
      content_type: file.mimetype,
    });

    if (!result.success) {
      throw new BadRequestException(result.message || 'Document processing failed');
    }

    // 3. Store in Project.metadata.documents (NestJS handles DB update)
    const project = await this.prisma.project.findUnique({
      where: { id: projectId },
      select: { metadata: true },
    });

    const metadata = (project?.metadata as ProjectMetadata) || {};
    const documents = metadata.documents || [];

    const documentEntry = {
      asset_id: result.asset_id,
      filename: result.filename,
      s3_url: result.s3_url,
      file_type: result.file_type,
      language: result.language,
      is_code_file: result.is_code_file,
      summary: result.summary,
      total_chunks: result.total_chunks,
      token_count: result.token_count,
      rag_processed: result.rag_processed,
      added_at: new Date().toISOString(),
    };

    await this.prisma.project.update({
      where: { id: projectId },
      data: {
        metadata: {
          ...metadata,
          documents: [...documents, documentEntry],
        },
      },
    });

    return result;
  }

  /**
   * Upload and process image
   */
  async uploadImage(
    userId: string,
    projectId: string,
    file: Express.Multer.File
  ) {
    // 1. Upload to S3
    const s3Url = await this.s3Service.uploadFile(file, {
      folder: `projects/${projectId}/images`,
    });

    // 2. Process via Python
    const result = await this.pythonApi.processImage({
      s3_url: s3Url,
      filename: file.originalname,
      session_id: projectId,
      content_type: file.mimetype,
    });

    if (!result.success) {
      throw new BadRequestException(result.message || 'Image processing failed');
    }

    // 3. Store in Project.metadata.images (NestJS handles DB update)
    const project = await this.prisma.project.findUnique({
      where: { id: projectId },
      select: { metadata: true },
    });

    const metadata = (project?.metadata as ProjectMetadata) || {};
    const images = metadata.images || [];

    const imageEntry = {
      asset_id: result.asset_id,
      filename: result.filename,
      s3_url: result.s3_url,
      image_url: result.image_url,
      analysis: result.analysis,
      rag_processed: result.rag_processed,
      added_at: new Date().toISOString(),
    };

    await this.prisma.project.update({
      where: { id: projectId },
      data: {
        metadata: {
          ...metadata,
          images: [...images, imageEntry],
        },
      },
    });

    return result;
  }
}
```

### 4. Controller Examples

```typescript
// projects.controller.ts
import {
  Controller,
  Post,
  Get,
  Body,
  Param,
  UseGuards,
  Sse,
  MessageEvent,
} from '@nestjs/common';
import { ProjectsService } from './projects.service';
import { AssetsService } from './assets.service';
import { Observable } from 'rxjs';

@Controller('projects')
export class ProjectsController {
  constructor(
    private readonly projectsService: ProjectsService,
    private readonly assetsService: AssetsService
  ) {}

  @Post()
  async createProject(@Body() createDto: CreateProjectDto, @User() user) {
    return this.projectsService.createProject(user.id, createDto);
  }

  @Get(':id/resume')
  async resumeProject(@Param('id') projectId: string, @User() user) {
    return this.projectsService.resumeProject(user.id, projectId);
  }

  @Post(':id/pause')
  async pauseProject(
    @Param('id') projectId: string,
    @Body() pauseDto: { timeout?: number },
    @User() user
  ) {
    return this.projectsService.pauseProject(user.id, projectId, pauseDto.timeout);
  }

  @Sse(':id/chat')
  streamChat(
    @Param('id') projectId: string,
    @Body() chatDto: ChatDto,
    @User() user
  ): Observable<MessageEvent> {
    return this.projectsService.sendChatMessage(
      user.id,
      projectId,
      chatDto.message,
      chatDto.options
    );
  }

  @Post(':id/assets/documents')
  async uploadDocument(
    @Param('id') projectId: string,
    @UploadedFile() file: Express.Multer.File,
    @User() user
  ) {
    return this.assetsService.uploadDocument(user.id, projectId, file);
  }

  @Post(':id/assets/images')
  async uploadImage(
    @Param('id') projectId: string,
    @UploadedFile() file: Express.Multer.File,
    @User() user
  ) {
    return this.assetsService.uploadImage(user.id, projectId, file);
  }
}
```

---

## ⚠️ Error Handling

### Common Error Scenarios

1. **Sandbox Creation Fails**
   - Python returns error → NestJS should handle gracefully
   - Project exists in DB but `sandbox_state` remains `NONE`
   - Consider retry logic or manual recovery

2. **Document Processing Fails**
   - Python returns `success: false` → NestJS should not update metadata
   - Return error to user, allow retry

3. **Chat Stream Errors**
   - SSE stream sends `error` event → Forward to frontend
   - Don't update DB (agent state managed by Python)

### Error Response Format

```typescript
// Python API errors
{
  detail: string; // Error message
}

// NestJS should handle and convert to standard format
{
  statusCode: number;
  message: string;
  error?: string;
}
```

---

## ✅ Best Practices

### 1. Database Updates

- ✅ **Always update DB from Python API responses** (even if Python also updates)
- ✅ **Update `last_active` on every interaction**
- ✅ **Handle state transitions properly** (NONE → RUNNING → PAUSED → RUNNING)
- ✅ **Use transactions** for related updates when possible

### 2. Sandbox Lifecycle

- ✅ **Check `sandbox_state` before operations**
- ✅ **Handle `KILLED` state** (sandbox expired >30 days, need new sandbox)
- ✅ **Monitor `last_active`** for auto-pause logic (optional)

### 3. Asset Processing

- ✅ **Process documents/images before chat** (for RAG context)
- ✅ **Store processing results immediately** in `Project.metadata`
- ✅ **Filter `rag_processed: true`** when sending `document_context` to chat

### 4. Chat/Agent Interaction

- ✅ **Stream SSE events to frontend** (don't buffer)
- ✅ **Extract metadata before chat** (documents/images from Project)
- ✅ **Don't update DB during chat** (Python manages agent state)

### 5. Error Recovery

- ✅ **Handle Python API failures gracefully**
- ✅ **Maintain DB consistency** even if Python operations fail
- ✅ **Log errors** for debugging and monitoring

---

## 🔧 Configuration

### Environment Variables

**NestJS Side**:
```env
PYTHON_API_URL=http://localhost:8000
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
```

**Python Side** (separate service):
```env
E2B_API_KEY=your_e2b_key
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
REDIS_URL=redis://localhost:6379
MONGODB_URI=mongodb://localhost:27017/agent_db
OPENROUTER_API_KEY=your_key
# ... other API keys
```

---

## 📝 Complete Integration Checklist

### Phase 1: Setup
- [ ] Install NestJS HTTP client (`@nestjs/axios` or `@nestjs/axios`)
- [ ] Configure Python API base URL
- [ ] Set up Prisma schema matching Python DB schema
- [ ] Create PythonApiService

### Phase 2: Project Management
- [ ] Implement `createProject()` with sandbox creation
- [ ] Implement `resumeProject()` with sandbox session
- [ ] Implement `pauseProject()` with sandbox pause
- [ ] Add DB update logic after each Python API call

### Phase 3: Asset Processing
- [ ] Implement S3 upload service
- [ ] Implement document processing flow
- [ ] Implement image processing flow
- [ ] Store results in `Project.metadata`

### Phase 4: Chat Integration
- [ ] Implement SSE streaming for chat
- [ ] Extract document/image context from metadata
- [ ] Forward SSE events to frontend
- [ ] Handle chat errors gracefully

### Phase 5: Testing
- [ ] Test new project creation flow
- [ ] Test existing project resume flow
- [ ] Test document processing → chat flow
- [ ] Test error scenarios
- [ ] Verify DB state consistency

---

## 🚀 Quick Start

1. **Copy service files** to your NestJS project
2. **Update Prisma schema** to match Project model
3. **Configure environment variables**
4. **Import PythonApiModule** in your AppModule
5. **Use services in your controllers**

That's it! The Python backend is now fully integrated with proper separation of concerns.

---

## 📚 Additional Resources

- [API Documentation](./API_DOCUMENTATION.md) - Complete API reference
- [Sandbox Database Approach](./sandbox/SANDBOX_DATABASE_INTEGRATED_APPROACH.md) - Sandbox architecture details
- Python Backend Codebase - For implementation details

---

**Last Updated**: 2025-01-XX


