"""NUMA Capture — Enums and type literals.

All string constants centralized here so the codebase uses Enums
instead of raw strings.
"""

from __future__ import annotations

from enum import Enum


class SessionStatus(str, Enum):
    """Status of an interview session."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

    @property
    def label(self) -> str:
        return {
            "pending": "Pendiente",
            "in_progress": "En Progreso",
            "completed": "Completada",
        }[self.value]


class Phase(str, Enum):
    """The five interview phases in order."""
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"

    @property
    def name_(self) -> str:
        return {
            "A": "Role Mapping & Gap Detection",
            "B": "Critical Incidents",
            "C": "Inverse Verification",
            "D": "The Unwritten",
            "E": "Negative Knowledge & Anti-Patterns",
        }[self.value]

    @property
    def color(self) -> str:
        return {
            "A": "#3b82f6",
            "B": "#f59e0b",
            "C": "#22c55e",
            "D": "#a855f7",
            "E": "#ef4444",
        }[self.value]

    @property
    def order(self) -> int:
        return {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}[self.value]


PHASE_ORDER: list[Phase] = [Phase.A, Phase.B, Phase.C, Phase.D, Phase.E]


class KnowledgeCategory(str, Enum):
    """Category of a knowledge item."""
    FACT = "fact"
    JUDGMENT = "judgment"
    INTUITION = "intuition"
    PATTERN = "pattern"
    GAP = "gap"

    @property
    def default_weight(self) -> float:
        return {
            "fact": 0.3,
            "judgment": 0.7,
            "intuition": 0.5,
            "pattern": 0.6,
            "gap": 0.8,
        }[self.value]


class EntityType(str, Enum):
    """Types of entities in the industrial knowledge graph."""
    MACHINE = "machine"
    PROCEDURE = "procedure"
    INCIDENT = "incident"
    SAFETY_RULE = "safety_rule"
    REGULATION = "regulation"
    ROLE = "role"
    MATERIAL = "material"
    TOOL = "tool"
    ALARM = "alarm"
    AREA = "area"
    RISK = "risk"

    @property
    def icon(self) -> str:
        return {
            "machine": "🏭",
            "procedure": "📋",
            "incident": "🚨",
            "safety_rule": "🛡️",
            "regulation": "📜",
            "role": "👤",
            "material": "🧪",
            "tool": "🔧",
            "alarm": "🔔",
            "area": "📍",
            "risk": "⚠️",
        }[self.value]


class RelationType(str, Enum):
    """Types of relations between industrial entities."""
    OPERATES = "operates"
    FOLLOWS = "follows"
    CAUSED_BY = "caused_by"
    PREVENTED_BY = "prevented_by"
    REQUIRES = "requires"
    LOCATED_IN = "located_in"
    REGULATED_BY = "regulated_by"
    TRIGGERS = "triggers"
    USES = "uses"
    PROCESSES = "processes"
    PART_OF = "part_of"
    ADJACENT_TO = "adjacent_to"
    HAS_RISK = "has_risk"
    PREVENTS = "prevents"


class ShadowCategory(str, Enum):
    """Category of a shadow entry."""
    DECISION = "decision"
    OBSERVATION = "observation"
    TIP = "tip"
    WARNING = "warning"

    @property
    def label(self) -> str:
        return {
            "decision": "Decisión",
            "observation": "Observación",
            "tip": "Truco",
            "warning": "Alerta",
        }[self.value]


class ShadowSource(str, Enum):
    """Source of a shadow entry."""
    QUICK = "quick"
    SCHEDULED = "scheduled"
    FOLLOWUP = "followup"


class MessageRole(str, Enum):
    """Role of a chat message."""
    ASSISTANT = "assistant"
    USER = "user"
