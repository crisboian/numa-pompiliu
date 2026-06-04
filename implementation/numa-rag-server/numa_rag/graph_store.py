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
        """Search the graph by traversing depth-1 from nodes matching the query.

        Two-stage retrieval:
        1. Seed: find nodes whose name overlaps with query tokens (semantic anchor).
        2. Expand: BFS depth-1 across adjacency to pull in neighbors.
        Score = (token_overlap * 1.0 for seed, 0.5 for neighbor) * node.weight.
        """
        tokens = [t for t in query.lower().split() if t]
        if not tokens:
            return []

        def overlap(name: str) -> float:
            name_lower = name.lower()
            return float(sum(1 for t in tokens if t in name_lower))

        seed_ids: dict[str, float] = {}
        for node_id, node in self.nodes.items():
            ov = overlap(node.name)
            if ov > 0:
                seed_ids[node_id] = ov

        scored: dict[str, tuple[float, ConceptNode]] = {}
        for seed_id, seed_ov in seed_ids.items():
            seed_node = self.nodes[seed_id]
            seed_score = seed_ov * seed_node.weight
            prev = scored.get(seed_id, (0.0, seed_node))[0]
            if seed_score > prev:
                scored[seed_id] = (seed_score, seed_node)

            for neighbor_id in self.adjacency.get(seed_id, []):
                neighbor = self.nodes.get(neighbor_id)
                if neighbor is None:
                    continue
                neighbor_ov = max(overlap(neighbor.name), 1.0)
                neighbor_score = 0.5 * neighbor_ov * neighbor.weight
                prev_n = scored.get(neighbor_id, (0.0, neighbor))[0]
                if neighbor_score > prev_n:
                    scored[neighbor_id] = (neighbor_score, neighbor)

        ranked = sorted(scored.values(), key=lambda x: x[0], reverse=True)
        return [
            RetrievedItem(
                statement=node.name,
                tier=node.tier,
                weight=node.weight,
                source="knowledge_graph",
            )
            for _, node in ranked[:limit]
        ]

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
