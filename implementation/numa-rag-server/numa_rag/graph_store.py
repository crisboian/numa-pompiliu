"""Graph store — lightweight in-memory knowledge graph for structural retrieval.

When Graphify is available via MCP, delegates to it.
Otherwise uses an internal SimpleGraph.
"""

from __future__ import annotations

import logging
from typing import Sequence

from numa_rag.knowledge import (
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    KnowledgeDocument,
    RetrievedItem,
    Tier,
)

logger = logging.getLogger(__name__)

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class SimpleGraph:
    """Lightweight in-memory knowledge graph."""

    def __init__(self) -> None:
        self.nodes: dict[str, ConceptNode] = {}
        self.edges: list[ConceptEdge] = []
        self.adjacency: dict[str, list[str]] = {}

    def load(self, doc: KnowledgeDocument) -> None:
        """Load nodes and edges from a KnowledgeDocument."""
        for node in doc.concept_graph.nodes:
            self.nodes[node.id] = node
        for edge in doc.concept_graph.edges:
            self.edges.append(edge)
            self.adjacency.setdefault(edge.source, []).append(edge.target)
            self.adjacency.setdefault(edge.target, []).append(edge.source)
        # Also create nodes from knowledge statements
        for stmt in doc.all_statements():
            node_id = stmt.id
            self.nodes[node_id] = ConceptNode(
                id=node_id,
                name=stmt.statement[:60],
                type_="statement",
                tier=stmt.tier,
                weight=stmt.weight,
            )

    def search(self, query: str, limit: int = 10) -> list[RetrievedItem]:
        """Search the graph by matching node names against query tokens.

        A simple keyword-based search on node names and statement text.
        """
        query_lower = query.lower()
        tokens = query_lower.split()
        scored: list[tuple[float, RetrievedItem]] = []

        for node_id, node in self.nodes.items():
            name_lower = node.name.lower()
            score = 0.0
            for token in tokens:
                if token in name_lower:
                    score += 1.0
                if name_lower.startswith(token) or name_lower.endswith(token):
                    score += 0.5
            if score > 0:
                scored.append(
                    (
                        score * node.weight,
                        RetrievedItem(
                            statement=node.name,
                            tier=node.tier,
                            weight=node.weight,
                            source="knowledge_graph",
                        ),
                    )
                )

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def stats(self) -> dict[str, int]:
        return {"nodes": len(self.nodes), "edges": len(self.edges)}


class GraphStore:
    """Graph store that prefers Graphify MCP, falls back to SimpleGraph."""

    def __init__(self, graphify_url: str = "") -> None:
        self.graphify_url = graphify_url
        self.fallback = SimpleGraph()
        self._use_fallback = True

    def load_document(self, doc: KnowledgeDocument) -> None:
        """Load knowledge into the graph."""
        self.fallback.load(doc)

    def search(self, query: str, limit: int = 10) -> list[RetrievedItem]:
        """Search graph for items matching the query."""
        return self.fallback.search(query, limit)

    def stats(self) -> dict[str, int]:
        return self.fallback.stats()
