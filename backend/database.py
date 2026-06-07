"""NUMA Capture Web — async database models and session management.

Uses SQLAlchemy 2.0 async with aiosqlite for proper non-blocking DB access.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship, selectinload

DATABASE_URL = "sqlite+aiosqlite:///./numa_capture.db"

async_engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


# ─── Tables ────────────────────────────────────────────────────────────────


class Session(Base):
    """An interview session."""

    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    expert_name = Column(String(255), default="")
    expert_role = Column(String(255), default="")
    domain = Column(String(255), default="")
    organization = Column(String(255), default="")

    current_phase = Column(String(1), default="A")  # A, B, C, D, E
    phase_order = Column(Integer, default=0)
    status = Column(String(32), default="pending")

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime, nullable=True)

    messages = relationship(
        "Message",
        back_populates="session",
        order_by="Message.created_at",
        cascade="all, delete-orphan",
    )
    knowledge_items = relationship(
        "KnowledgeItem",
        back_populates="session",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "expert_name": self.expert_name,
            "expert_role": self.expert_role,
            "domain": self.domain,
            "organization": self.organization,
            "current_phase": self.current_phase,
            "phase_order": self.phase_order,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "message_count": len(self.messages or []),
            "knowledge_count": len(self.knowledge_items or []),
        }


class Message(Base):
    """A message in the interview conversation."""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    phase = Column(String(1), nullable=False)
    order = Column(Integer, default=0)
    tags = Column(String(512), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    session = relationship("Session", back_populates="messages")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "phase": self.phase,
            "order": self.order,
            "tags": self.tags.split(",") if self.tags else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class KnowledgeItem(Base):
    """A knowledge item extracted during capture."""

    __tablename__ = "knowledge_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    statement = Column(Text, nullable=False)
    category = Column(String(64), default="fact")
    weight = Column(Float, default=0.5)
    phase = Column(String(1), nullable=False)
    rationale = Column(Text, default="")
    conditions = Column(Text, default="[]")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    session = relationship("Session", back_populates="knowledge_items")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "category": self.category,
            "weight": self.weight,
            "phase": self.phase,
            "rationale": self.rationale,
            "conditions": (json.loads(self.conditions) if self.conditions else []),
        }


class ShadowEntry(Base):
    """A quick shadow capture — record a decision in <30 seconds."""

    __tablename__ = "shadow_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    expert_name = Column(String(255), default="")
    content = Column(Text, nullable=False)
    category = Column(String(64), default="decision")
    context = Column(String(512), default="")
    tags = Column(String(512), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    source = Column(String(32), default="quick")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "expert_name": self.expert_name,
            "content": self.content,
            "category": self.category,
            "context": self.context,
            "tags": self.tags.split(",") if self.tags else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "source": self.source,
        }


class SafetyReport(Base):
    """A safety/security report uploaded by the user. Text extracted for LLM processing."""

    __tablename__ = "safety_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    file_size = Column(Integer, default=0)
    content_type = Column(String(64), default="application/octet-stream")
    text_content = Column(Text, default="")
    status = Column(String(32), default="uploaded")
    processing_error = Column(String(512), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "original_filename": self.original_filename,
            "file_size": self.file_size,
            "content_type": self.content_type,
            "text_content": self.text_content[:500] if self.text_content else "",
            "status": self.status,
            "processing_error": self.processing_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class IndustrialEntity(Base):
    """An entity in the industrial knowledge graph."""

    __tablename__ = "industrial_entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(64), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    attributes = Column(Text, default="{}")
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "name": self.name,
            "description": self.description,
            "attributes": json.loads(self.attributes) if self.attributes else {},
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class IndustrialRelation(Base):
    """A relation between two industrial entities."""

    __tablename__ = "industrial_relations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("industrial_entities.id"), nullable=False)
    target_id = Column(Integer, ForeignKey("industrial_entities.id"), nullable=False)
    relation_type = Column(String(64), nullable=False)
    weight = Column(Float, default=1.0)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    source = relationship("IndustrialEntity", foreign_keys=[source_id])
    target = relationship("IndustrialEntity", foreign_keys=[target_id])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "weight": self.weight,
            "notes": self.notes,
        }


# ─── Init / Session helpers ───────────────────────────────────────────────


async def init_db() -> None:
    """Create all tables (async)."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def init_db_sync() -> None:
    """Create all tables synchronously (for tests / CLI)."""
    # Use the same metadata on a sync engine for table creation
    from sqlalchemy import create_engine
    sync_url = DATABASE_URL.replace("sqlite+aiosqlite:///", "sqlite:///")
    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=sync_engine)
    sync_engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_session_with_data(
    db: AsyncSession, session_id: str
) -> Session | None:
    """Get a session with eagerly-loaded messages and knowledge items."""
    result = await db.execute(
        select(Session)
        .options(selectinload(Session.messages), selectinload(Session.knowledge_items))
        .where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session:
        # Ensure relationships are populated before session closes
        _ = session.messages
        _ = session.knowledge_items
    return session
