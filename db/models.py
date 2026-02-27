# db/models.py - SIMPLIFIED ARCHITECTURE
"""
Database Models - Simplified Session Management
==============================================

SIMPLIFIED ARCHITECTURE:
- Project = Session (One-to-One mapping)
- project.id is used as session_id everywhere
- Direct relationship: User -> Projects -> Files/Snapshots

USAGE:
- Agno session_id = project.id
- E2B sandbox_id = project.id
- Database queries use project.id
- Session restoration uses project.id
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String,
    Integer,
    Text,
    DateTime,
    Boolean,
    Enum,
    ForeignKey,
    Index,
    UniqueConstraint,
    JSON,
    PrimaryKeyConstraint,
    ForeignKeyConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
import uuid
import enum


class Base(AsyncAttrs, DeclarativeBase):
    """Base model for all tables"""

    pass


def generate_uuid():
    return str(uuid.uuid4())


# =============================================================================
# ENUMS (UPPERCASE to match Prisma)
# =============================================================================


class ProjectType(str, enum.Enum):
    GAME = "GAME"
    FULLSTACK = "FULLSTACK"
    LANDING_PAGE = "LANDING_PAGE"
    CODE_ANALYSIS = "CODE_ANALYSIS"


class SandboxState(str, enum.Enum):
    RUNNING = "RUNNING"  # Changed from "running" to match Prisma
    PAUSED = "PAUSED"  # Changed from "paused" to match Prisma
    KILLED = "KILLED"  # Changed from "killed" to match Prisma
    NONE = "NONE"  # Changed from "none" to match Prisma


class SessionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"  # Changed from "active" to match Prisma
    PAUSED = "PAUSED"  # Changed from "paused" to match Prisma
    ENDED = "ENDED"  # Changed from "ended" to match Prisma


# =============================================================================
# USER MODEL
# =============================================================================


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="users_pkey"),
        Index("users_walletAddress_key", "walletAddress", unique=True),
    )

    # Core fields - matching Prisma schema exactly
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    wallet_address: Mapped[str] = mapped_column(
        "walletAddress",  # ✅ Prisma camelCase column name
        String,
        unique=True,
        nullable=False,
    )

    # Payment and status fields - Prisma camelCase
    current_plan: Mapped[str] = mapped_column(
        "currentPlan",  # ✅ Prisma camelCase column name
        String(13),
        default="FREE",
        nullable=False,
    )
    customer_id: Mapped[Optional[str]] = mapped_column(
        "customerId", String, nullable=True  # ✅ Prisma camelCase column name
    )
    status: Mapped[str] = mapped_column(String(7), default="ACTIVE", nullable=False)
    current_payment_method_id: Mapped[Optional[str]] = mapped_column(
        "currentPaymentMethodId",  # ✅ Prisma camelCase column name
        String,
        nullable=True,
    )

    # GitHub integration - Prisma camelCase
    github_token: Mapped[Optional[str]] = mapped_column(
        "githubToken", String, nullable=True  # ✅ Prisma camelCase column name
    )
    github_username: Mapped[Optional[str]] = mapped_column(
        "githubUsername", String, nullable=True  # ✅ Prisma camelCase column name
    )

    # Timestamps - Prisma uses camelCase (TIMESTAMP precision=3 to match model.py)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",  # ✅ Prisma camelCase column name
        TIMESTAMP(precision=3),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",  # ✅ Prisma camelCase column name
        TIMESTAMP(precision=3),
        nullable=False,
    )

    # Relationships
    Project: Mapped[list["Project"]] = relationship(
        "Project", back_populates="users", cascade="all, delete-orphan"
    )


class Project(Base):
    """
    Project = Session (Simplified Architecture)

    Each project represents a continuous working session.
    Project ID is used as:
    - Database identifier
    - Agno session_id
    - E2B sandbox identifier
    - Session restoration identifier
    """

    __tablename__ = "Project"  # Prisma uses capital P
    __table_args__ = (
        ForeignKeyConstraint(
            ["userId"],
            ["users.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="Project_userId_fkey",
        ),
        PrimaryKeyConstraint("id", name="Project_pkey"),
        Index("Project_type_idx", "type"),
        Index("ix_projects_user_id", "userId"),
    )

    # PRIMARY KEY - Use this as session_id everywhere!
    id: Mapped[str] = mapped_column(String, primary_key=True)

    # User relationship - Prisma uses userId (camelCase)
    user_id: Mapped[str] = mapped_column(
        "userId", String, nullable=False  # ✅ Prisma camelCase column name
    )

    # Project metadata
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Project type - Use enum for type safety
    type: Mapped[str] = mapped_column(
        Enum(
            "GAME",
            "FULLSTACK",
            "LANDING_PAGE",
            "CODE_ANALYSIS",
            name="ProjectType",
            native_enum=False,
            create_constraint=False,
        ),
        default="GAME",
        nullable=False,
        index=True,
    )

    # E2B Sandbox tracking - Prisma camelCase
    active_sandbox_id: Mapped[Optional[str]] = mapped_column(
        "active_sandbox_id",  # ✅ Prisma uses snake_case here (from schema)
        String,
        nullable=True,
    )
    # Sandbox state - Prisma camelCase
    sandbox_state: Mapped[str] = mapped_column(
        "sandbox_state",  # ✅ Prisma uses snake_case here (from schema)
        Enum(
            "RUNNING",
            "PAUSED",
            "KILLED",
            "NONE",
            name="SandboxState",
            native_enum=False,
            create_constraint=False,
        ),
        default="NONE",
        nullable=False,
    )

    # Session status (merged from Session table)
    status: Mapped[str] = mapped_column(
        Enum(
            "ACTIVE",
            "PAUSED",
            "ENDED",
            name="SessionStatus",
            native_enum=False,
            create_constraint=False,
        ),
        default="ACTIVE",
        nullable=False,
    )

    # Timestamps - Prisma uses snake_case for these in Project table (TIMESTAMP precision=6 to match model.py)
    created_at: Mapped[datetime] = mapped_column(
        "created_at",  # ✅ Prisma snake_case (from schema)
        TIMESTAMP(precision=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",  # ✅ Prisma snake_case (from schema)
        TIMESTAMP(precision=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_active: Mapped[datetime] = mapped_column(
        "last_active",  # ✅ Prisma snake_case (from schema)
        TIMESTAMP(precision=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        "ended_at",  # ✅ Prisma snake_case (from schema)
        TIMESTAMP(precision=6),
        nullable=True,
    )

    # Metadata field (JSONB to match model.py)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)

    # Relationships (removed sessions relationship - Project IS the session)
    users: Mapped["User"] = relationship("User", back_populates="Project")
    ProjectFile: Mapped[list["ProjectFile"]] = relationship(
        "ProjectFile", back_populates="project", cascade="all, delete-orphan"
    )
    ProjectThought: Mapped[list["ProjectThought"]] = relationship(
        "ProjectThought", back_populates="project", cascade="all, delete-orphan"
    )
    # project_snapshots removed - not used by either backend


class ProjectFile(Base):
    __tablename__ = "ProjectFile"  # Prisma uses capital P and camelCase

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    project_id: Mapped[str] = mapped_column(
        "project_id",  # ✅ Prisma snake_case (from schema)
        String,
        ForeignKey("Project.id", ondelete="CASCADE"),
        index=True,
    )

    # File metadata - Prisma snake_case
    file_path: Mapped[str] = mapped_column(
        "file_path", String(500), index=True  # ✅ Prisma snake_case (from schema)
    )
    content: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(
        "size_bytes", Integer, default=0  # ✅ Prisma snake_case (from schema)
    )
    mime_type: Mapped[Optional[str]] = mapped_column(
        "mime_type", String(100), nullable=True  # ✅ Prisma snake_case (from schema)
    )

    # Deletion tracking (soft delete) - Prisma snake_case
    is_deleted: Mapped[bool] = mapped_column(
        "is_deleted",  # ✅ Prisma snake_case (from schema)
        Boolean,
        default=False,
        index=True,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        "deleted_at",  # ✅ Prisma snake_case (from schema)
        TIMESTAMP(precision=6),
        nullable=True,
    )

    # Tracking - Prisma snake_case
    created_by_tool: Mapped[str] = mapped_column(
        "created_by_tool", String(100)  # ✅ Prisma snake_case (from schema)
    )
    created_at: Mapped[datetime] = mapped_column(
        "created_at",  # ✅ Prisma snake_case (from schema)
        TIMESTAMP(precision=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",  # ✅ Prisma snake_case (from schema)
        TIMESTAMP(precision=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="ProjectFile")

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"],
            ["Project.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="ProjectFile_project_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="ProjectFile_pkey"),
        Index("uq_project_file_path", "project_id", "file_path", unique=True),
    )


class ProjectThought(Base):
    """
    Agent thoughts for context management.
    Stores agent's internal reasoning and planning.
    """

    __tablename__ = "ProjectThought"  # Prisma uses capital P and camelCase

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    project_id: Mapped[str] = mapped_column(
        "project_id",  # ✅ Prisma snake_case (from schema)
        String,
        ForeignKey("Project.id", ondelete="CASCADE"),
        index=True,
    )

    # Thought content - Prisma snake_case
    thought: Mapped[str] = mapped_column(Text)
    thought_type: Mapped[str] = mapped_column(
        "thought_type",  # ✅ Prisma snake_case (from schema)
        String(50),
        default="planning",
    )

    # Organization - Prisma snake_case
    phase: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    milestone: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    priority: Mapped[str] = mapped_column(String(20), default="normal", index=True)

    # Timestamps (TIMESTAMP precision=6 to match model.py)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(precision=6), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="ProjectThought")

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"],
            ["Project.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="ProjectThought_project_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="ProjectThought_pkey"),
    )


# =============================================================================
# EXPORTS - Ensure all models are registered for Alembic autogenerate
# =============================================================================

__all__ = [
    "Base",
    "User",
    "Project",
    "ProjectFile",
    "ProjectThought",
    "ProjectType",
    "SandboxState",
    "SessionStatus",
]
