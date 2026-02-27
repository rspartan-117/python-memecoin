# db/data_access.py - Clean Data Access Layer
"""
Data access layer for database operations.
Pure CRUD operations without business logic.
"""

from sqlalchemy import select, func, desc, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, OperationalError, DatabaseError
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

from .models import (
    User,
    Project,
    ProjectFile,
    ProjectType,
    SandboxState,
    SessionStatus,
    ProjectThought,
)

logger = logging.getLogger(__name__)


class UserRepository:
    """Repository for user operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user(self, user_id: str) -> Optional[User]:
        """
        Get existing user by ID.

        IMPORTANT: This Python backend should NOT create users!
        Users should be created through the NestJS backend which manages
        wallet addresses, payments, and authentication.

        Args:
            user_id: The user ID to look up

        Returns:
            User if found, None otherwise

        Raises:
            ValueError: If user_id is not found (user must exist in NestJS first)
        """
        stmt = select(User).where(User.id == user_id)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            logger.error(
                f"❌ User {user_id} not found in database. "
                f"Users must be created through the NestJS backend first."
            )
            raise ValueError(
                f"User {user_id} does not exist. Please ensure the user is created "
                f"in the NestJS backend before using the Python agent backend."
            )

        logger.debug(f"✅ User {user_id} found: {user.wallet_address}")
        return user

    async def get_user_by_wallet(self, wallet_address: str) -> Optional[User]:
        """Get user by wallet address"""
        stmt = select(User).where(User.wallet_address == wallet_address)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class FileRepository:
    """Repository for file operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_project_file(
        self,
        project_id: str,
        file_path: str,
        content: str,
        created_by_tool: str = "write_file",
    ) -> ProjectFile:
        """Save project file - UPSERT operation"""
        now = (
            datetime.now()
        )  # Use naive datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE

        # use byte-length for accurate size accounting
        byte_size = len(content.encode("utf-8"))

        stmt = insert(ProjectFile).values(
            project_id=project_id,
            file_path=file_path,
            content=content,
            created_by_tool=created_by_tool,
            size_bytes=byte_size,
            created_at=now,
            updated_at=now,
        )

        # On conflict, update
        stmt = stmt.on_conflict_do_update(
            index_elements=["project_id", "file_path"],
            set_=dict(
                content=stmt.excluded.content,
                size_bytes=stmt.excluded.size_bytes,
                created_by_tool=stmt.excluded.created_by_tool,
                updated_at=now,
                is_deleted=False,
                deleted_at=None,
            ),
        ).returning(ProjectFile)

        result = await self.session.execute(stmt)
        project_file = result.scalar_one()
        await self.session.flush()
        return project_file

    async def get_project_file(
        self, project_id: str, file_path: str
    ) -> Optional[ProjectFile]:
        """Get a specific file from project"""
        stmt = select(ProjectFile).where(
            ProjectFile.project_id == project_id,
            ProjectFile.file_path == file_path,
            ProjectFile.is_deleted == False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_project_files(self, project_id: str) -> List[ProjectFile]:
        """Get all files for a project (excluding deleted)"""
        stmt = (
            select(ProjectFile)
            .where(
                ProjectFile.project_id == project_id, ProjectFile.is_deleted == False
            )
            .order_by(ProjectFile.file_path)
        )

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def delete_project_file(
        self, project_id: str, file_path: str, soft_delete: bool = True
    ) -> bool:
        """Delete a project file"""
        if soft_delete:
            stmt = select(ProjectFile).where(
                ProjectFile.project_id == project_id, ProjectFile.file_path == file_path
            )
            result = await self.session.execute(stmt)
            project_file = result.scalar_one_or_none()

            if project_file:
                project_file.is_deleted = True
                project_file.deleted_at = datetime.now()  # Use naive datetime
                await self.session.flush()
                return True
        else:
            stmt = delete(ProjectFile).where(
                ProjectFile.project_id == project_id, ProjectFile.file_path == file_path
            )
            result = await self.session.execute(stmt)
            return result.rowcount > 0

        return False

    async def get_project_file_count(self, project_id: str) -> int:
        """Get count of files in project"""
        stmt = select(func.count(ProjectFile.id)).where(
            ProjectFile.project_id == project_id, ProjectFile.is_deleted == False
        )
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0)

    async def save_multiple_files(
        self,
        project_id: str,
        files: Dict[str, str],
        created_by_tool: str = "batch_write",
    ) -> List[ProjectFile]:
        """Save multiple files efficiently"""
        saved_files = []
        for file_path, content in files.items():
            project_file = await self.save_project_file(
                project_id=project_id,
                file_path=file_path,
                content=content,
                created_by_tool=created_by_tool,
            )
            saved_files.append(project_file)
        return saved_files


class ProjectRepository:
    """Repository for project operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_project(
        self,
        user_id: str,
        project_id: str,
        project_name: str = "Default Project",
        description: str = None,
        project_type: str = ProjectType.GAME.value,
    ) -> Project:
        """Get existing project or create new one"""
        stmt = select(Project).where(Project.id == project_id)
        result = await self.session.execute(stmt)
        project = result.scalar_one_or_none()

        if not project:
            project = Project(
                id=project_id,
                user_id=user_id,
                name=project_name,
                description=description,
                type=project_type,
            )
            self.session.add(project)
            await self.session.flush()

        return project

    async def get_project(self, project_id: str) -> Optional[Project]:
        """Get project by ID"""
        stmt = select(Project).where(Project.id == project_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_sandbox_state(
        self, project_id: str, sandbox_id: Optional[str], state: SandboxState
    ):
        """Update project's sandbox information - Optimized with direct UPDATE"""
        stmt = (
            update(Project)
            .where(Project.id == project_id)
            .values(
                active_sandbox_id=sandbox_id,
                sandbox_state=state.value,  # Enum value
                updated_at=datetime.now(),
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def update_project_metadata(
        self,
        project_id: str,
        metadata: Dict[str, Any],
        merge: bool = True,
    ) -> bool:
        """
        Update project metadata.
        
        Args:
            project_id: Project identifier
            metadata: Metadata dict to set or merge
            merge: If True, merge with existing metadata. If False, replace entirely.
            
        Returns:
            True if successful, False if project not found
        """
        # Get current project to merge metadata if needed
        if merge:
            stmt = select(Project).where(Project.id == project_id)
            result = await self.session.execute(stmt)
            project = result.scalar_one_or_none()
            
            if not project:
                return False
            
            # Merge with existing metadata
            current_metadata = project.metadata_ or {}
            current_metadata.update(metadata)
            metadata = current_metadata
        
        # Use direct UPDATE for better performance
        stmt = (
            update(Project)
            .where(Project.id == project_id)
            .values(
                metadata_=metadata,
                updated_at=datetime.now(),
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def get_user_projects(self, user_id: str) -> List[Project]:
        """Get all projects for a user"""
        stmt = (
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(desc(Project.updated_at))
        )

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_project_status(self, project_id: str, status: SessionStatus):
        """Update project status - Optimized with direct UPDATE"""
        values = {
            "status": status.value,  # Enum value
            "updated_at": datetime.now(),
        }
        
        if status == SessionStatus.ENDED:
            values["ended_at"] = datetime.now()
        
        stmt = (
            update(Project)
            .where(Project.id == project_id)
            .values(**values)
        )
        await self.session.execute(stmt)
        await self.session.flush()


class ThoughtRepository:
    """Repository for thought operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_thought(
        self,
        project_id: str,
        thought: str,
        thought_type: str = "planning",
        phase: Optional[str] = None,
        milestone: Optional[str] = None,
        priority: str = "normal",
    ) -> ProjectThought:
        """Save a new thought - Removed manual commit (service layer handles transactions)"""
        thought_obj = ProjectThought(
            project_id=project_id,
            thought=thought,
            thought_type=thought_type,
            phase=phase,
            milestone=milestone,
            priority=priority,
        )
        self.session.add(thought_obj)
        await self.session.flush()  # Changed from commit() to flush()
        return thought_obj

    async def get_thoughts(
        self,
        project_id: str,
        thought_type: Optional[str] = None,
        phase: Optional[str] = None,
        limit: int = 10,
    ) -> List[ProjectThought]:
        """Get thoughts with optional filters"""
        stmt = select(ProjectThought).where(ProjectThought.project_id == project_id)

        if thought_type:
            stmt = stmt.where(ProjectThought.thought_type == thought_type)

        if phase:
            stmt = stmt.where(ProjectThought.phase == phase)

        stmt = stmt.order_by(desc(ProjectThought.timestamp)).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_milestones(
        self, project_id: str, limit: int = 20
    ) -> List[ProjectThought]:
        """Get milestone thoughts"""
        stmt = (
            select(ProjectThought)
            .where(
                ProjectThought.project_id == project_id,
                ProjectThought.milestone.isnot(None),
            )
            .order_by(desc(ProjectThought.timestamp))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_thoughts(self, project_id: str) -> int:
        """Count total thoughts"""
        stmt = select(func.count(ProjectThought.id)).where(
            ProjectThought.project_id == project_id
        )
        return await self.session.scalar(stmt)

    async def delete_old_thoughts(self, project_id: str, cutoff_date: datetime) -> int:
        """Delete thoughts older than cutoff date - Removed manual commit"""
        stmt = delete(ProjectThought).where(
            ProjectThought.project_id == project_id,
            ProjectThought.timestamp < cutoff_date,
        )
        result = await self.session.execute(stmt)
        await self.session.flush()  # Changed from commit() to flush()
        return result.rowcount
