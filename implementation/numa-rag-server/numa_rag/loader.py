"""Bridge between numa-capture JSON output and the RAG server stores.

Reads a KnowledgeDocument-shaped JSON produced by `numa_capture.output`,
converts it into the server's `KnowledgeDocument` model, and indexes it
into ChromaStore and GraphStore.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from numa_rag.chroma_store import ChromaStore
from numa_rag.graph_store import GraphStore
from numa_rag.knowledge import (
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    KnowledgeDocument,
    KnowledgeStatement,
    Tier,
)

logger = logging.getLogger(__name__)


def _statement_from_entry(entry: dict[str, Any], tier: Tier) -> KnowledgeStatement:
    """Convert a single capture knowledge entry to a KnowledgeStatement."""
    return KnowledgeStatement(
        id=entry.get("id", ""),
        statement=entry["statement"],
        tier=tier,
        weight=float(entry.get("weight", 0.0)),
        source=entry.get("source", ""),
        expert_name=entry.get("expert_name", ""),
        conditions=list(entry.get("conditions", [])),
    )


def parse_capture_document(payload: dict[str, Any]) -> KnowledgeDocument:
    """Parse a numa-capture JSON dict into a server-side KnowledgeDocument."""
    expert = payload.get("expert", {})
    session = payload.get("session", {})
    knowledge = payload.get("knowledge", {})
    graph_payload = payload.get("concept_graph", {"nodes": [], "edges": []})

    facts = [
        _statement_from_entry(e, Tier.FACTS)
        for e in knowledge.get("facts", [])
    ]
    judgments = [
        _statement_from_entry(e, Tier.JUDGMENTS)
        for e in knowledge.get("judgments", [])
    ]
    intuitions = [
        _statement_from_entry(e, Tier.INTUITIONS)
        for e in knowledge.get("intuitions", [])
    ]

    nodes = [
        ConceptNode(
            id=n["id"],
            name=n.get("name", n["id"]),
            type_=n.get("type_", "concept"),
        )
        for n in graph_payload.get("nodes", [])
    ]
    edges = [
        ConceptEdge(
            source=e["source"],
            target=e["target"],
            relation=e.get("relation", "related_to"),
            weight=float(e.get("weight", 1.0)),
        )
        for e in graph_payload.get("edges", [])
    ]

    return KnowledgeDocument(
        expert_name=expert.get("name", ""),
        expert_role=expert.get("role", ""),
        domain=expert.get("domain", ""),
        session_id=session.get("id") or f"session_loaded",
        facts=facts,
        judgments=judgments,
        intuitions=intuitions,
        concept_graph=ConceptGraph(nodes=nodes, edges=edges),
    )


def load_capture_payload(
    payload: dict[str, Any],
    chroma: ChromaStore,
    graph: GraphStore,
) -> dict[str, int]:
    """Index a capture document into the provided stores.

    Returns a small dict with `chunks_indexed`, `graph_nodes`, `graph_edges`.
    """
    doc = parse_capture_document(payload)
    chunks = chroma.add_knowledge(doc)
    graph.load_document(doc)

    g_stats = graph.stats()
    logger.info(
        "Loaded capture document: %d chunks, %d nodes, %d edges",
        chunks,
        g_stats.get("nodes", 0),
        g_stats.get("edges", 0),
    )
    return {
        "chunks_indexed": chunks,
        "graph_nodes": g_stats.get("nodes", 0),
        "graph_edges": g_stats.get("edges", 0),
    }


def load_capture_file(
    path: str | Path,
    chroma: ChromaStore,
    graph: GraphStore,
) -> dict[str, int]:
    """Read a capture JSON file from disk and index it."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return load_capture_payload(payload, chroma, graph)
