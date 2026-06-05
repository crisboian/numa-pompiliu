"""NUMA Capture Web — database models and session management."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

DATABASE_URL = "sqlite:///./numa_capture.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


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

    current_phase = Column(String(1), default="A")  # A, B, C, D
    phase_order = Column(Integer, default=0)  # question index within phase
    status = Column(String(32), default="pending")  # pending, in_progress, completed

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime, nullable=True)

    messages = relationship(
        "Message", back_populates="session", order_by="Message.created_at", cascade="all, delete-orphan"
    )
    knowledge_items = relationship(
        "KnowledgeItem", back_populates="session", cascade="all, delete-orphan"
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
            "message_count": len(self.messages),
            "knowledge_count": len(self.knowledge_items),
        }

    def phase_progress(self) -> dict[str, Any]:
        """Return progress per phase."""
        phases = {"A": 0, "B": 0, "C": 0, "D": 0}
        for m in self.messages:
            if m.phase in phases:
                phases[m.phase] += 1
        return phases


class Message(Base):
    """A message in the interview conversation."""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    role = Column(String(16), nullable=False)  # assistant, user
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
    category = Column(String(64), default="fact")  # fact, judgment, intuition, pattern, gap
    weight = Column(Float, default=0.5)
    phase = Column(String(1), nullable=False)
    rationale = Column(Text, default="")
    conditions = Column(Text, default="")  # JSON list
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
            "conditions": json.loads(self.conditions) if self.conditions else [],
        }


# ─── Init ──────────────────────────────────────────────────────────────────


def init_db() -> None:
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Yield a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
