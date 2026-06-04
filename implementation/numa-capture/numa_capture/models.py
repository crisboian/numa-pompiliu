"""NUMA Capture — data models for the interview pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Phase(str, Enum):
    A = "mapping"
    B = "critical_cases"
    C = "inverse_verification"
    D = "the_unwritten"


PHASE_DURATIONS: dict[Phase, int] = {
    Phase.A: 30,
    Phase.B: 90,
    Phase.C: 60,
    Phase.D: 30,
}

PHASE_DESCRIPTIONS: dict[Phase, str] = {
    Phase.A: "Role mapping and gap detection",
    Phase.B: "Top 10 critical cases with decision rationale",
    Phase.C: "Inverse verification — challenge testimony against documentation",
    Phase.D: "The Unwritten — knowledge in no document",
}


class LLMPrompt(BaseModel):
    """A prompt used in an interview phase."""

    id: str = Field(default_factory=lambda: f"prompt_{uuid.uuid4().hex[:8]}")
    phase: Phase
    text: str
    order: int = 0
    tags: list[str] = Field(default_factory=list)


class KnowledgeItem(BaseModel):
    """Extracted knowledge from a phase."""

    id: str = Field(default_factory=lambda: f"ki_{uuid.uuid4().hex[:8]}")
    statement: str
    category: str = "fact"
    weight: float = 0.3
    conditions: list[str] = Field(default_factory=list)
    phase: Phase
    rationale: str = ""
    source_question: str = ""


class PhaseResult(BaseModel):
    """Output from a single interview phase."""

    phase: Phase
    duration_minutes: int
    status: str = "pending"
    concepts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    knowledge_items: list[KnowledgeItem] = Field(default_factory=list)
    notes: str = ""
    transcript: list[dict[str, str]] = Field(default_factory=list)


class InterviewSession(BaseModel):
    """A complete NUMA Capture interview session."""

    session_id: str = Field(
        default_factory=lambda: f"capture_{uuid.uuid4().hex[:8]}"
    )
    expert_name: str = ""
    expert_role: str = ""
    domain: str = ""
    date: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )
    phases: dict[str, PhaseResult] = Field(default_factory=dict)
    status: str = "created"
    total_duration_minutes: int = 0

    def add_phase(self, result: PhaseResult) -> None:
        self.phases[result.phase.value] = result
        self.total_duration_minutes = sum(
            p.duration_minutes for p in self.phases.values()
        )
