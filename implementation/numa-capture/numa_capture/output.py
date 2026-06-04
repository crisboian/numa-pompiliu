"""NUMA Capture — output export (JSON knowledge document)."""

from __future__ import annotations

import json
from typing import Any

from numa_capture.models import InterviewSession, KnowledgeItem


def to_knowledge_document(session: InterviewSession) -> dict[str, Any]:
    """Convert a completed interview session to a structured knowledge document.

    The output matches the schema expected by NUMA Structure protocol:
    - facts, judgments, intuitions with tier weights
    - concept graph with nodes and edges
    - session metadata
    """
    facts: list[dict] = []
    judgments: list[dict] = []
    intuitions: list[dict] = []

    for phase_name, phase in session.phases.items():
        for item in phase.knowledge_items:
            entry = {
                "id": item.id,
                "statement": item.statement,
                "source": f"interview_phase_{phase_name}",
                "expert_name": session.expert_name,
                "conditions": item.conditions,
                "rationale": item.rationale,
                "phase": phase_name,
            }

            if item.category == "fact" or item.category == "verified_fact":
                entry["weight"] = 0.3
                facts.append(entry)
            elif item.category == "judgment" or item.category == "pattern":
                entry["weight"] = 0.7
                judgments.append(entry)
            elif item.category == "gap":
                entry["weight"] = 0.5
                intuitions.append(entry)
            elif item.category == "intuition":
                entry["weight"] = 0.5
                intuitions.append(entry)
            else:
                entry["weight"] = 0.3
                facts.append(entry)

    # Build concept graph
    concept_nodes = []
    concept_edges = []
    seen_concepts: set[str] = set()
    for phase in session.phases.values():
        for concept in phase.concepts:
            if concept not in seen_concepts:
                seen_concepts.add(concept)
                concept_nodes.append({"id": concept, "name": concept, "type_": "concept"})

    doc = {
        "document_id": f"numa_knowledge_{session.session_id}",
        "expert": {
            "name": session.expert_name,
            "role": session.expert_role,
            "domain": session.domain,
        },
        "session": {
            "id": session.session_id,
            "date": session.date,
            "duration_minutes": session.total_duration_minutes,
            "status": session.status,
        },
        "knowledge": {
            "facts": facts,
            "judgments": judgments,
            "intuitions": intuitions,
        },
        "concept_graph": {
            "nodes": concept_nodes,
            "edges": concept_edges,
        },
        "statistics": {
            "total_items": len(facts) + len(judgments) + len(intuitions),
            "phases_completed": len(session.phases),
        },
    }

    return doc


def export_to_file(session: InterviewSession, filepath: str) -> str:
    """Export session to a JSON file."""
    doc = to_knowledge_document(session)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    return filepath
