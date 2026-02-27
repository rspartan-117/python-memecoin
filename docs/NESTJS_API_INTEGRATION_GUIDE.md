# Complete API Integration Guide for NestJS Backend

## Overview

This FastAPI Landing Page Generation Agent provides a streaming API for AI-powered landing page creation using LangGraph, E2B sandboxes, and PostgreSQL for state persistence.

**Base URL**: `http://localhost:8000` (configure as needed)

---

## 📋 Table of Contents

1. [Authentication](#authentication)
2. [Core Endpoints](#core-endpoints)
3. [Request/Response Structures](#requestresponse-structures)
4. [Server-Sent Events (SSE)](#server-sent-events-sse)
5. [NestJS Integration Example](#nestjs-integration-example)
6. [Error Handling](#error-handling)

---

## 🔐 Authentication

Currently, this API does not implement authentication headers. User identification is done via request body parameters (`user_id`, `email_id`).

For production, you may want to add:

- JWT tokens in Authorization header
- API keys
- OAuth2

---

## 🎯 Core Endpoints

### 1. Start Chat Session (Streaming)

**Endpoint**: `POST /api/projects/{project_id}/chat`

**Description**: Main streaming endpoint for AI agent interaction. Returns Server-Sent Events (SSE) stream.

**Path Parameters**:

- `project_id` (string, required): Unique project identifier

**Request Body**:

```typescript
{
  message: string;        // User message/instruction to the AI agent
  user_id: string;        // Unique user identifier
  project_id: string;     // Must match path parameter
  email_id?: string;      // User email (default: "user@system.local")
}
```

**Example Request**:

```json
{
  "message": "Create a todo app with FastAPI and Next.js",
  "user_id": "user_123",
  "project_id": "kjegfihifeojgbjhv",
  "email_id": "user@example.com"
}
```

**Response Type**: `text/event-stream` (Server-Sent Events)

**Response Headers**:

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

**SSE Event Types** (see detailed section below):

- `agent_start` - Agent begins processing
- `agent_thinking` - AI thinking tokens (streaming text)
- `tool_start` - Tool execution begins
- `tool_complete` - Tool execution completes
- `tool_calling` - Tool is being called
- `agent_complete` - Agent finishes processing
- `error` - Error occurred

---

### 2. Get Conversation History

**Endpoint**: `GET /api/projects/{project_id}/history`

**Description**: Retrieve complete conversation history for a project with message serialization.

**Path Parameters**:

- `project_id` (string, required): Project identifier

**Response**:

```typescript
{
  project_id: string;
  messages: Array<{
    role: string;              // "human" | "ai" | "tool"
    content: string;           // Message content
    timestamp: string | null;  // ISO 8601 timestamp
    tool_calls?: Array<{       // Present if AI called tools
      id: string;
      name: string;
      args: object;
    }>;
    tool_name?: string;        // Present if this is a tool result
  }>;
  message_count: number;
  current_phase: string | null;  // "planning" | "backend_dev" | "frontend_dev" | "integration"
  next_steps: string[] | null;
}
```

**Example Response**:

```json
{
  "project_id": "kjegfihifeojgbjhv",
  "messages": [
    {
      "role": "human",
      "content": "Create a todo app",
      "timestamp": "2025-11-03T10:30:00.000Z"
    },
    {
      "role": "ai",
      "content": "I'll create a todo app with FastAPI backend and Next.js frontend.",
      "timestamp": "2025-11-03T10:30:05.000Z",
      "tool_calls": [
        {
          "id": "tool_123",
          "name": "write_file",
          "args": {
            "file_path": "backend/main.py",
            "content": "from fastapi import FastAPI..."
          }
        }
      ]
    },
    {
      "role": "tool",
      "content": "File written successfully",
      "tool_name": "write_file",
      "timestamp": "2025-11-03T10:30:06.000Z"
    }
  ],
  "message_count": 3,
  "current_phase": "backend_dev",
  "next_steps": ["Create database models", "Add CRUD endpoints"]
}
```

---

### 3. Get Project Files

**Endpoint**: `GET /api/projects/{project_id}/files`

**Description**: Retrieve all files created/modified in the project.

**Path Parameters**:

- `project_id` (string, required): Project identifier

**Response**:

```typescript
{
  files: {
    [filePath: string]: {
      content: string;
      size_bytes: number;
      created_at: string;      // ISO 8601
      updated_at: string;      // ISO 8601
      mime_type?: string;
      created_by_tool: string;
    }
  };
  file_count: number;
}
```

**Example Response**:

```json
{
  "files": {
    "backend/main.py": {
      "content": "from fastapi import FastAPI\n\napp = FastAPI()...",
      "size_bytes": 1024,
      "created_at": "2025-11-03T10:30:00.000Z",
      "updated_at": "2025-11-03T10:35:00.000Z",
      "mime_type": "text/x-python",
      "created_by_tool": "write_file"
    },
    "frontend/pages/index.tsx": {
      "content": "import React from 'react'...",
      "size_bytes": 2048,
      "created_at": "2025-11-03T10:40:00.000Z",
      "updated_at": "2025-11-03T10:40:00.000Z",
      "mime_type": "text/typescript",
      "created_by_tool": "write_file"
    }
  },
  "file_count": 2
}
```

---

### 4. Get Agent State

**Endpoint**: `GET /api/projects/{project_id}/state`

**Description**: Get detailed current state of the AI agent for a project.

**Path Parameters**:

- `project_id` (string, required): Project identifier

**Response**:

```typescript
{
  project_id: string;
  status: "active" | "no_state";
  timestamp: string;              // ISO 8601
  summary: {
    phase: string;                // Current development phase
    iteration: number;            // Current iteration count
    errors: number;               // Error count
    next_steps: number;           // Number of planned next steps
    recent_thoughts: number;      // Recent thinking count
    active_files: number;         // Number of active files
    running_services: number;     // Running services count
    total_tokens: number;         // Total tokens used
    estimated_cost: string;       // Cost estimate (e.g., "$0.0450")
  };
  details: {
    current_phase: string | null;
    next_phase: string | null;
    next_steps: string[];
    recent_thinking: Array<{
      thought: string;
      timestamp: string;
    }>;
    last_error: string | null;
    active_files: string[];
    service_pids: {
      [serviceName: string]: number;
    };
    working_directory: string;
    tokens_used: {
      total_input: number;
      total_output: number;
    };
    iteration_count: number;
    last_summarized_at: string | null;
  };
  checkpoint_info: {
    checkpoint_id: string | null;
    thread_id: string;
  };
}
```

**Example Response**:

```json
{
  "project_id": "kjegfihifeojgbjhv",
  "status": "active",
  "timestamp": "2025-11-03T10:45:00.000Z",
  "summary": {
    "phase": "backend_dev",
    "iteration": 12,
    "errors": 0,
    "next_steps": 3,
    "recent_thoughts": 5,
    "active_files": 8,
    "running_services": 2,
    "total_tokens": 15000,
    "estimated_cost": "$0.0450"
  },
  "details": {
    "current_phase": "backend_dev",
    "next_phase": "frontend_dev",
    "next_steps": [
      "Create user authentication endpoints",
      "Add database migration",
      "Test API endpoints"
    ],
    "recent_thinking": [
      {
        "thought": "Need to implement user registration",
        "timestamp": "2025-11-03T10:44:00.000Z"
      }
    ],
    "last_error": null,
    "active_files": [
      "backend/main.py",
      "backend/models.py",
      "backend/database.py"
    ],
    "service_pids": {
      "backend": 1234,
      "frontend": 5678
    },
    "working_directory": "/home/user/code",
    "tokens_used": {
      "total_input": 8000,
      "total_output": 7000
    },
    "iteration_count": 12,
    "last_summarized_at": "2025-11-03T10:40:00.000Z"
  },
  "checkpoint_info": {
    "checkpoint_id": "checkpoint_abc123",
    "thread_id": "kjegfihifeojgbjhv"
  }
}
```

---

### 5. Get Quick State Summary

**Endpoint**: `GET /api/projects/{project_id}/state/summary`

**Description**: Lightweight version of state - just essential metrics.

**Path Parameters**:

- `project_id` (string, required): Project identifier

**Response**:

```typescript
{
  project_id: string;
  exists: boolean;
  timestamp?: string;
  phase?: string;
  iteration?: number;
  errors?: number;
  next_steps?: number;
  recent_thoughts?: number;
  active_files?: number;
  running_services?: number;
  total_tokens?: number;
}
```

---

### 6. Restore Project

**Endpoint**: `POST /api/projects/{project_id}/restore`

**Description**: Restore project files, install dependencies, and start services.

**Path Parameters**:

- `project_id` (string, required): Project identifier

**Request Body**:

```typescript
{
  user_id: string; // User identifier
}
```

**Response**:

```typescript
{
  success: boolean;
  status: "completed" | "partial" | "error";
  message: string;
  data: {
    files_restored: number;
    sandbox_id: string;
    dependencies: {
      installed: {
        npm: boolean;
        pip: boolean;
        yarn: boolean;
        pnpm: boolean;
      };
      errors: Array<{
        type: string;
        error: string;
      }>;
    };
    services: {
      backend?: {
        started: boolean;
        url: string;          // e.g., "http://8000-sandbox.e2b.dev"
        port: number;
        pid: number;
        type: string;         // "fastapi" | "express" | "flask"
        file?: string;
      };
      frontend?: {
        started: boolean;
        url: string;          // e.g., "http://3000-sandbox.e2b.dev"
        port: number;
        pid: number;
        type: string;         // "nextjs" | "react" | "vue"
      };
    };
    incomplete_code: boolean;
  };
  errors: Array<{
    type: string;
    file?: string;
    error: string;
  }>;
}
```

**Example Response**:

```json
{
  "success": true,
  "status": "completed",
  "message": "Project fully restored and activated!",
  "data": {
    "files_restored": 15,
    "sandbox_id": "sandbox_abc123",
    "dependencies": {
      "installed": {
        "npm": true,
        "pip": true,
        "yarn": false,
        "pnpm": false
      },
      "errors": []
    },
    "services": {
      "backend": {
        "started": true,
        "url": "http://8000-sandbox.e2b.dev",
        "port": 8000,
        "pid": 1234,
        "type": "fastapi",
        "file": "main.py"
      },
      "frontend": {
        "started": true,
        "url": "http://3000-sandbox.e2b.dev",
        "port": 3000,
        "pid": 5678,
        "type": "nextjs"
      }
    },
    "incomplete_code": false
  },
  "errors": []
}
```

---

### 7. Get User Projects

**Endpoint**: `GET /api/users/{user_id}/projects`

**Description**: List all projects for a user with pagination.

**Path Parameters**:

- `user_id` (string, required): User identifier

**Query Parameters**:

- `status` (string, optional): Filter by status ("active" | "ended")
- `limit` (number, optional): Max results (default: 50)
- `offset` (number, optional): Pagination offset (default: 0)

**Response**:

```typescript
{
  user_id: string;
  projects: Array<{
    project_id: string;
    name: string;
    status: "active" | "paused" | "ended";
    created_at: string | null; // ISO 8601
    last_active: string | null; // ISO 8601
  }>;
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}
```

**Example Response**:

```json
{
  "user_id": "user_123",
  "projects": [
    {
      "project_id": "kjegfihifeojgbjhv",
      "name": "Todo App",
      "status": "active",
      "created_at": "2025-11-03T10:00:00.000Z",
      "last_active": "2025-11-03T10:45:00.000Z"
    },
    {
      "project_id": "project_456",
      "name": "E-commerce Site",
      "status": "active",
      "created_at": "2025-11-02T14:30:00.000Z",
      "last_active": "2025-11-03T09:15:00.000Z"
    }
  ],
  "total": 2,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

---

### 8. Health Check

**Endpoint**: `GET /health`

**Description**: Check API health status.

**Response**:

```typescript
{
  status: "healthy" | "degraded";
  timestamp: string; // ISO 8601
  services: {
    checkpointer: {
      status: "healthy" | "unhealthy";
      // ... additional checkpointer info
    }
    database: {
      status: "healthy";
      initialized: boolean;
    }
  }
}
```

---

## 📡 Server-Sent Events (SSE)

The chat endpoint returns a stream of Server-Sent Events. Each event has a type and data payload.

### Event Format

```
event: <event_type>
data: <json_payload>

```

### Event Types and Payloads

#### 1. `agent_start`

Agent begins processing the request.

```typescript
{
  timestamp: string; // ISO 8601
  project_id: string;
}
```

#### 2. `agent_thinking`

AI agent is thinking - returns tokens as they're generated (streaming).

```typescript
{
  token: string; // Text token/chunk
  node: string; // Current node name in agent graph
}
```

#### 3. `tool_start`

Agent is calling a tool.

```typescript
{
  tool_name: string; // e.g., "write_file", "read_file"
  tool_id: string; // Unique tool call ID
  tool_args: object; // Arguments passed to tool
  node: string; // Current node name
}
```

**Example**:

```json
{
  "tool_name": "write_file",
  "tool_id": "call_abc123",
  "tool_args": {
    "file_path": "backend/main.py",
    "content": "from fastapi import FastAPI..."
  },
  "node": "agent"
}
```

#### 4. `tool_complete`

Tool execution completed.

```typescript
{
  tool_name: string;
  output_preview: string; // First 200 chars of output
  node: string;
}
```

#### 5. `tool_calling`

Tool is being invoked (from content blocks).

```typescript
{
  tool_name: string;
  tool_id: string;
  node: string;
}
```

#### 6. `agent_complete`

Agent finished processing.

```typescript
{
  timestamp: string; // ISO 8601
  project_id: string;
}
```

#### 7. `error`

Error occurred during processing.

```typescript
{
  message: string;
  type: string; // Error type/class name
  timestamp: string; // ISO 8601
}
```

---

## 🎨 NestJS Integration Example

### 1. Create DTOs

```typescript
// src/game-agent/dto/chat-request.dto.ts
export class ChatRequestDto {
  message: string;
  user_id: string;
  project_id: string;
  email_id?: string;
}

// src/game-agent/dto/restore-request.dto.ts
export class RestoreRequestDto {
  user_id: string;
}

// src/game-agent/dto/project-query.dto.ts
export class ProjectQueryDto {
  status?: "active" | "ended";
  limit?: number = 50;
  offset?: number = 0;
}
```

### 2. Create Interfaces

```typescript
// src/game-agent/interfaces/agent-response.interface.ts

export interface MessageResponse {
  role: string;
  content: string;
  timestamp: string | null;
  tool_calls?: ToolCall[];
  tool_name?: string;
}

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, any>;
}

export interface ProjectHistoryResponse {
  project_id: string;
  messages: MessageResponse[];
  message_count: number;
  current_phase: string | null;
  next_steps: string[] | null;
}

export interface AgentStateResponse {
  project_id: string;
  status: "active" | "no_state";
  timestamp: string;
  summary: {
    phase: string;
    iteration: number;
    errors: number;
    next_steps: number;
    recent_thoughts: number;
    active_files: number;
    running_services: number;
    total_tokens: number;
    estimated_cost: string;
  };
  details: {
    current_phase: string | null;
    next_phase: string | null;
    next_steps: string[];
    recent_thinking: Array<{ thought: string; timestamp: string }>;
    last_error: string | null;
    active_files: string[];
    service_pids: Record<string, number>;
    working_directory: string;
    tokens_used: {
      total_input: number;
      total_output: number;
    };
    iteration_count: number;
    last_summarized_at: string | null;
  };
  checkpoint_info: {
    checkpoint_id: string | null;
    thread_id: string;
  };
}

export interface RestoreResponse {
  success: boolean;
  status: "completed" | "partial" | "error";
  message: string;
  data: {
    files_restored: number;
    sandbox_id: string;
    dependencies: {
      installed: {
        npm: boolean;
        pip: boolean;
        yarn: boolean;
        pnpm: boolean;
      };
      errors: Array<{ type: string; error: string }>;
    };
    services: {
      backend?: ServiceInfo;
      frontend?: ServiceInfo;
    };
    incomplete_code: boolean;
  };
  errors: Array<{ type: string; file?: string; error: string }>;
}

export interface ServiceInfo {
  started: boolean;
  url: string;
  port: number;
  pid: number;
  type: string;
  file?: string;
}

// SSE Event Types
export interface SSEEvent {
  event: string;
  data: any;
}

export interface AgentStartEvent {
  timestamp: string;
  project_id: string;
}

export interface AgentThinkingEvent {
  token: string;
  node: string;
}

export interface ToolStartEvent {
  tool_name: string;
  tool_id: string;
  tool_args: Record<string, any>;
  node: string;
}

export interface ToolCompleteEvent {
  tool_name: string;
  output_preview: string;
  node: string;
}

export interface AgentCompleteEvent {
  timestamp: string;
  project_id: string;
}

export interface ErrorEvent {
  message: string;
  type: string;
  timestamp: string;
}
```

### 3. Create Service

```typescript
// src/game-agent/game-agent.service.ts
import { Injectable, HttpService } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { Observable } from "rxjs";
import { map } from "rxjs/operators";
import {
  ChatRequestDto,
  RestoreRequestDto,
  ProjectQueryDto,
  ProjectHistoryResponse,
  AgentStateResponse,
  RestoreResponse,
} from "./dto";

@Injectable()
export class GameAgentService {
  private readonly baseUrl: string;

  constructor(
    private readonly httpService: HttpService,
    private readonly configService: ConfigService
  ) {
    this.baseUrl = this.configService.get<string>(
      "GAME_AGENT_API_URL",
      "http://localhost:8000"
    );
  }

  /**
   * Start a streaming chat session
   * Returns an Observable that emits SSE events
   */
  startChat(projectId: string, chatRequest: ChatRequestDto): Observable<any> {
    const url = `${this.baseUrl}/api/projects/${projectId}/chat`;

    return this.httpService
      .post(url, chatRequest, {
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        responseType: "stream",
      })
      .pipe(map((response) => response.data));
  }

  /**
   * Get conversation history
   */
  async getHistory(projectId: string): Promise<ProjectHistoryResponse> {
    const url = `${this.baseUrl}/api/projects/${projectId}/history`;
    const response = await this.httpService.get(url).toPromise();
    return response.data;
  }

  /**
   * Get project files
   */
  async getProjectFiles(projectId: string): Promise<any> {
    const url = `${this.baseUrl}/api/projects/${projectId}/files`;
    const response = await this.httpService.get(url).toPromise();
    return response.data;
  }

  /**
   * Get agent state
   */
  async getAgentState(projectId: string): Promise<AgentStateResponse> {
    const url = `${this.baseUrl}/api/projects/${projectId}/state`;
    const response = await this.httpService.get(url).toPromise();
    return response.data;
  }

  /**
   * Get quick state summary
   */
  async getStateSummary(projectId: string): Promise<any> {
    const url = `${this.baseUrl}/api/projects/${projectId}/state/summary`;
    const response = await this.httpService.get(url).toPromise();
    return response.data;
  }

  /**
   * Restore project
   */
  async restoreProject(
    projectId: string,
    restoreRequest: RestoreRequestDto
  ): Promise<RestoreResponse> {
    const url = `${this.baseUrl}/api/projects/${projectId}/restore`;
    const response = await this.httpService
      .post(url, restoreRequest)
      .toPromise();
    return response.data;
  }

  /**
   * Get user projects
   */
  async getUserProjects(userId: string, query: ProjectQueryDto): Promise<any> {
    const url = `${this.baseUrl}/api/users/${userId}/projects`;
    const response = await this.httpService
      .get(url, {
        params: query,
      })
      .toPromise();
    return response.data;
  }

  /**
   * Health check
   */
  async healthCheck(): Promise<any> {
    const url = `${this.baseUrl}/health`;
    const response = await this.httpService.get(url).toPromise();
    return response.data;
  }
}
```

### 4. Create Controller

```typescript
// src/game-agent/game-agent.controller.ts
import {
  Controller,
  Post,
  Get,
  Body,
  Param,
  Query,
  Sse,
  MessageEvent,
} from "@nestjs/common";
import { Observable } from "rxjs";
import { GameAgentService } from "./game-agent.service";
import { ChatRequestDto, RestoreRequestDto, ProjectQueryDto } from "./dto";

@Controller("game-agent")
export class GameAgentController {
  constructor(private readonly gameAgentService: GameAgentService) {}

  /**
   * Start streaming chat session
   * SSE endpoint that streams events from the AI agent
   */
  @Sse("projects/:projectId/chat")
  streamChat(
    @Param("projectId") projectId: string,
    @Body() chatRequest: ChatRequestDto
  ): Observable<MessageEvent> {
    return this.gameAgentService.startChat(projectId, chatRequest);
  }

  /**
   * Get conversation history
   */
  @Get("projects/:projectId/history")
  async getHistory(@Param("projectId") projectId: string) {
    return this.gameAgentService.getHistory(projectId);
  }

  /**
   * Get project files
   */
  @Get("projects/:projectId/files")
  async getProjectFiles(@Param("projectId") projectId: string) {
    return this.gameAgentService.getProjectFiles(projectId);
  }

  /**
   * Get agent state
   */
  @Get("projects/:projectId/state")
  async getAgentState(@Param("projectId") projectId: string) {
    return this.gameAgentService.getAgentState(projectId);
  }

  /**
   * Get quick state summary
   */
  @Get("projects/:projectId/state/summary")
  async getStateSummary(@Param("projectId") projectId: string) {
    return this.gameAgentService.getStateSummary(projectId);
  }

  /**
   * Restore project
   */
  @Post("projects/:projectId/restore")
  async restoreProject(
    @Param("projectId") projectId: string,
    @Body() restoreRequest: RestoreRequestDto
  ) {
    return this.gameAgentService.restoreProject(projectId, restoreRequest);
  }

  /**
   * Get user projects
   */
  @Get("users/:userId/projects")
  async getUserProjects(
    @Param("userId") userId: string,
    @Query() query: ProjectQueryDto
  ) {
    return this.gameAgentService.getUserProjects(userId, query);
  }

  /**
   * Health check
   */
  @Get("health")
  async healthCheck() {
    return this.gameAgentService.healthCheck();
  }
}
```

### 5. Create Module

```typescript
// src/game-agent/game-agent.module.ts
import { Module, HttpModule } from "@nestjs/common";
import { ConfigModule } from "@nestjs/config";
import { GameAgentController } from "./game-agent.controller";
import { GameAgentService } from "./game-agent.service";

@Module({
  imports: [HttpModule, ConfigModule],
  controllers: [GameAgentController],
  providers: [GameAgentService],
  exports: [GameAgentService],
})
export class GameAgentModule {}
```

### 6. Environment Configuration

```env
# .env
GAME_AGENT_API_URL=http://localhost:8000
```

### 7. Usage Example in Another Service

```typescript
// src/app/app.service.ts
import { Injectable } from "@nestjs/common";
import { GameAgentService } from "./game-agent/game-agent.service";

@Injectable()
export class AppService {
  constructor(private readonly gameAgentService: GameAgentService) {}

  async createGameProject(userId: string, projectId: string, prompt: string) {
    // Start the AI agent chat
    const chatStream = this.gameAgentService.startChat(projectId, {
      message: prompt,
      user_id: userId,
      project_id: projectId,
      email_id: "user@example.com",
    });

    // Subscribe to events
    chatStream.subscribe({
      next: (event) => {
        console.log("Received event:", event);
        // Handle different event types
        // You can emit these to WebSocket clients, save to DB, etc.
      },
      error: (err) => {
        console.error("Stream error:", err);
      },
      complete: () => {
        console.log("Agent finished");
      },
    });
  }

  async getProjectStatus(projectId: string) {
    // Get current agent state
    const state = await this.gameAgentService.getAgentState(projectId);

    // Get conversation history
    const history = await this.gameAgentService.getHistory(projectId);

    // Get files
    const files = await this.gameAgentService.getProjectFiles(projectId);

    return {
      state,
      history,
      files,
    };
  }

  async restoreExistingProject(userId: string, projectId: string) {
    // Restore project with all files and services
    const result = await this.gameAgentService.restoreProject(projectId, {
      user_id: userId,
    });

    if (result.success) {
      console.log("Project restored!");
      console.log("Backend URL:", result.data.services.backend?.url);
      console.log("Frontend URL:", result.data.services.frontend?.url);
    }

    return result;
  }
}
```

---

## ⚠️ Error Handling

### HTTP Error Responses

All endpoints may return standard HTTP error responses:

```typescript
{
  statusCode: number;        // 400, 404, 500, etc.
  message: string;           // Error message
  error?: string;            // Error type
  detail?: string;           // Detailed error information
}
```

### Common Error Codes

- `400 Bad Request` - Invalid request parameters or body
- `404 Not Found` - Project or user not found
- `500 Internal Server Error` - Server-side error

### SSE Error Event

Errors during streaming are sent as `error` events:

```typescript
{
  event: "error",
  data: {
    message: string;
    type: string;
    timestamp: string;
  }
}
```

### Best Practices

1. **Always validate** `project_id` matches in body and path
2. **Handle SSE reconnection** on client side
3. **Implement timeout** for long-running operations
4. **Store project_id** for session continuity
5. **Check agent state** before starting new operations
6. **Handle incomplete_code** flag in restore responses

---

## 📊 Data Flow

### Typical Usage Flow

1. **Create/Start Project**

   ```
   POST /api/projects/{project_id}/chat
   -> Returns SSE stream with progress
   ```

2. **Monitor Progress**

   ```
   GET /api/projects/{project_id}/state
   -> Check current phase, iteration, errors
   ```

3. **View Generated Code**

   ```
   GET /api/projects/{project_id}/files
   -> Get all files with content
   ```

4. **Continue Conversation**

   ```
   POST /api/projects/{project_id}/chat (with new message)
   -> Agent continues from last checkpoint
   ```

5. **Restore Later**
   ```
   POST /api/projects/{project_id}/restore
   -> Restore files + start services
   ```

---

## 🔧 Configuration Notes

### Required Environment Variables (in the FastAPI service)

- `ANTHROPIC_API_KEY` - Claude AI API key
- `E2B_API_KEY` - E2B sandbox API key
- `DATABASE_URL` - PostgreSQL connection string
- `DIRECT_DATABASE_URL` - Direct PostgreSQL connection (for migrations)

### Optional Environment Variables

- `REDIS_URL` - Redis for caching
- `OPENAI_API_KEY` - For middleware summarization
- `LANGSMITH_API_KEY` - For tracing/monitoring

---

## 📝 Notes

1. **Thread ID**: `project_id` is used as `thread_id` in LangGraph for conversation continuity
2. **State Persistence**: Conversation history is automatically saved to PostgreSQL
3. **Sandbox Isolation**: Each (user_id, project_id) gets isolated E2B sandbox
4. **Streaming**: Use SSE for real-time updates; events arrive as agent executes
5. **File Tracking**: All file changes are tracked in database
6. **Service URLs**: Restore endpoint returns live URLs for backend/frontend when services start successfully

---

## 🚀 Quick Start for NestJS

1. Copy the DTOs, interfaces, service, controller, and module files
2. Add `GAME_AGENT_API_URL` to your `.env`
3. Import `GameAgentModule` in your `AppModule`
4. Inject `GameAgentService` where needed
5. Use the service methods to interact with the API

That's it! The API is now fully integrated into your NestJS backend.
