"""NUMA RAG Server — data models for knowledge representation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Tier(str, Enum):
    """Knowledge tier classification with retrieval weights."""

    FACTS = "facts"
    JUDGMENTS = "judgments"
    INTUITIONS = "intuitions"


TIER_WEIGHTS: dict[Tier, float] = {
    Tier.FACTS: 0.3,
    Tier.JUDGMENTS: 0.7,
    Tier.INTUITIONS: 0.5,
}

TIER_SOURCES: dict[Tier, str] = {
    Tier.FACTS: "Manuals, SOPs, regulations",
    Tier.JUDGMENTS: "Expert interview (decisions with rationale)",
    Tier.INTUITIONS: "Expert narrative (heuristics, unwritten knowledge)",
}


class KnowledgeStatement(BaseModel):
    """A single knowledge statement with tier classification."""

    id: str = Field(default_factory=lambda: f"ks_{uuid.uuid4().hex[:12]}")
    statement: str
    tier: Tier
    weight: float = Field(default=0.0)
    source: str
    expert_name: str = ""
    session_id: str = ""
    conditions: list[str] = Field(default_factory=list)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if self.weight == 0.0:
            self.weight = TIER_WEIGHTS.get(self.tier, 0.3)


class ConceptNode(BaseModel):
    """A node in the knowledge concept graph."""

    id: str
    name: str
    type_: str = "concept"
    tier: Tier = Tier.FACTS
    weight: float = 0.3


class ConceptEdge(BaseModel):
    """An edge connecting two concept nodes."""

    source: str
    target: str
    relation: str = "related_to"
    weight: float = 1.0


class ConceptGraph(BaseModel):
    """Graph of concepts extracted from expert knowledge."""

    nodes: list[ConceptNode] = Field(default_factory=list)
    edges: list[ConceptEdge] = Field(default_factory=list)


class KnowledgeDocument(BaseModel):
    """Complete knowledge document from a capture session."""

    expert_name: str
    expert_role: str = ""
    domain: str = ""
    session_id: str = Field(default_factory=lambda: f"session_{uuid.uuid4().hex[:8]}")
    facts: list[KnowledgeStatement] = Field(default_factory=list)
    judgments: list[KnowledgeStatement] = Field(default_factory=list)
    intuitions: list[KnowledgeStatement] = Field(default_factory=list)
    concept_graph: ConceptGraph = Field(default_factory=ConceptGraph)
    capture_date: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )
    version: int = 1

    def all_statements(self) -> list[KnowledgeStatement]:
        return self.facts + self.judgments + self.intuitions


class RetrievedItem(BaseModel):
    """A single item returned from retrieval."""

    statement: str
    tier: Tier
    weight: float
    source: str
    expert_name: str = ""
    conditions: list[str] = Field(default_factory=list)
    graph_rank: int | None = None
    vector_rank: int | None = None
    rrf_score: float = 0.0
    final_score: float = 0.0


class KGAAResult(BaseModel):
    """Result of a kgaa_search query."""

    query: str
    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    confidence: str = "medium"
    latency_ms: float = 0.0
    recommendations: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
