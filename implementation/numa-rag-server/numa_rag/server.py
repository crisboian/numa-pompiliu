"""NUMA RAG Server — MCP server exposing kgaa_search tool.

Implements the Model Context Protocol (MCP) over stdio transport,
providing a single kgaa_search tool that fuses graph traversal
and vector search via Reciprocal Rank Fusion.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from numa_rag.chroma_store import ChromaStore
from numa_rag.graph_store import GraphStore
from numa_rag.knowledge import (
    KGAAResult,
    KnowledgeDocument,
    KnowledgeStatement,
    RetrievedItem,
    Tier,
)
from numa_rag.rrf import compute_rrf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("numa-rag-server")

# ─── Sample knowledge document from the paper ──────────────────────────────

SAMPLE_DOC = KnowledgeDocument(
    expert_name="Pepe García",
    expert_role="Senior Operator, K-700 Line",
    domain="Industrial Safety",
    session_id="session_20260315",
    facts=[
        KnowledgeStatement(
            id="fact_001",
            statement="K-700 operating range: 170–190°C per manual.",
            tier=Tier.FACTS,
            source="Manual K-700 p.34",
        ),
        KnowledgeStatement(
            id="fact_002",
            statement="Incident #234 (2019): right gasket melted at 193°C.",
            tier=Tier.FACTS,
            source="Incident report #234",
        ),
        KnowledgeStatement(
            id="fact_003",
            statement="Standard startup procedure takes 15 minutes.",
            tier=Tier.FACTS,
            source="SOP K-700 v3.2",
        ),
    ],
    judgments=[
        KnowledgeStatement(
            id="judgment_001",
            statement="Never exceed 185°C even though the manual says 190°C. The right-hand gasket is softer than specification.",
            tier=Tier.JUDGMENTS,
            source="Interview Phase B — Critical Cases",
            expert_name="Pepe García",
            conditions=["gasket_type_2019", "right_side"],
            weight=0.7,
        ),
        KnowledgeStatement(
            id="judgment_002",
            statement="On cold-start Mondays (ambient temp < 5°C), reduce calibration temperature to 175°C.",
            tier=Tier.JUDGMENTS,
            source="Interview Phase C — Inverse Verification",
            expert_name="Pepe García",
            conditions=["ambient_temp < 5°C", "monday_morning"],
            weight=0.7,
        ),
        KnowledgeStatement(
            id="judgment_003",
            statement="After a major maintenance cycle, run the calibration cycle twice before production.",
            tier=Tier.JUDGMENTS,
            source="Interview Phase B — Critical Cases",
            expert_name="Pepe García",
            conditions=["after_major_maintenance"],
            weight=0.7,
        ),
    ],
    intuitions=[
        KnowledgeStatement(
            id="intuition_001",
            statement="Listen for a clicking sound on startup — that means the right gasket is binding.",
            tier=Tier.INTUITIONS,
            source="Interview Phase D — The Unwritten",
            expert_name="Pepe García",
            weight=0.5,
        ),
        KnowledgeStatement(
            id="intuition_002",
            statement="If the pressure gauge needle vibrates between 1.2–1.4 bar during warm-up, a valve seal is degrading.",
            tier=Tier.INTUITIONS,
            source="Interview Phase D — The Unwritten",
            expert_name="Pepe García",
            weight=0.5,
        ),
    ],
    concept_graph={
        "nodes": [
            {"id": "K-700", "name": "K-700 Machine", "type_": "equipment"},
            {"id": "gasket", "name": "Right Gasket", "type_": "component"},
            {"id": "calibration", "name": "Calibration Process", "type_": "process"},
            {"id": "temp_range", "name": "Temperature Range", "type_": "parameter"},
            {"id": "pressure", "name": "Pressure Gauge", "type_": "component"},
        ],
        "edges": [
            {"source": "K-700", "target": "gasket", "relation": "contains"},
            {"source": "gasket", "target": "calibration", "relation": "affected_by"},
            {"source": "calibration", "target": "temp_range", "relation": "defines"},
            {"source": "gasket", "target": "temp_range", "relation": "limited_by"},
        ],
    },
)


class NumaRAGServer:
    """MCP server for NUMA knowledge retrieval."""

    def __init__(self) -> None:
        self.chroma = ChromaStore()
        self.graph = GraphStore()
        self._cache: dict[str, tuple[float, KGAAResult]] = {}
        self._cache_ttl = 300  # 5 minutes
        self._initialized = False

    def initialize(self) -> None:
        """Load sample knowledge and build indexes."""
        if self._initialized:
            return

        logger.info("Initializing NUMA RAG server with sample knowledge...")
        n_indexed = self.chroma.add_knowledge(SAMPLE_DOC)
        self.graph.load_document(SAMPLE_DOC)
        stats_c = self.chroma.stats()
        stats_g = self.graph.stats()
        self._initialized = True
        logger.info(
            "Initialized: %d chunks, %d graph nodes, %d edges",
            stats_c.get("chunks", 0),
            stats_g.get("nodes", 0),
            stats_g.get("edges", 0),
        )

    def kgaa_search(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Execute hybrid search: graph + vector → RRF → weighted response.

        This is the main search tool exposed via MCP.

        Args:
            query: Natural language question.
            limit: Maximum number of sources to return.

        Returns:
            Dict with answer, sources, confidence, latency_ms, recommendations.
        """
        # Ensure initialized
        if not self._initialized:
            self.initialize()

        # Check cache
        cache_key = query.strip().lower()
        if cache_key in self._cache:
            cached_at, result = self._cache[cache_key]
            if time.time() - cached_at < self._cache_ttl:
                result.latency_ms = 0.0  # cached — no latency
                return result.model_dump()

        start = time.time()

        # Step 1: Graph search
        graph_results = self.graph.search(query, limit=limit * 2)

        # Step 2: Vector search
        vector_results = self.chroma.search(query, limit=limit * 2)

        # Step 3: RRF fusion
        fused = compute_rrf(graph_results, vector_results)
        top_k = fused[:limit]

        # Step 4: Build response
        answer = self._build_answer(query, top_k)
        sources = self._build_sources(top_k)
        conditions = self._collect_conditions(top_k)
        recommendations = self._build_recommendations(top_k)
        confidence = self._determine_confidence(top_k)

        latency = (time.time() - start) * 1000

        result = KGAAResult(
            query=query,
            answer=answer,
            sources=sources,
            confidence=confidence,
            latency_ms=round(latency, 1),
            recommendations=recommendations,
            conditions=conditions,
        )

        # Cache
        self._cache[cache_key] = (time.time(), result)

        return result.model_dump()

    def _build_answer(self, query: str, items: list[RetrievedItem]) -> str:
        """Assemble a natural-language answer from the top items."""
        if not items:
            return "No relevant knowledge found. Consider expanding the query or checking the knowledge base."

        parts: list[str] = []
        for item in items:
            tier_label = item.tier.value.capitalize()
            source_info = f" ({item.expert_name + ', ' if item.expert_name else ''}{item.source})" if item.source else ""
            parts.append(
                f"**{tier_label}**{source_info}:\n"
                f"\"{item.statement}\""
            )

        return "\n\n".join(parts)

    def _build_sources(self, items: list[RetrievedItem]) -> list[dict[str, Any]]:
        """Format sources for the response."""
        sources = []
        for item in items:
            src = {
                "statement": item.statement,
                "tier": item.tier.value,
                "weight": item.weight,
                "source": item.source,
            }
            if item.expert_name:
                src["expert_name"] = item.expert_name
            if item.conditions:
                src["conditions"] = item.conditions
            if item.rrf_score > 0:
                src["rrf_score"] = round(item.rrf_score, 4)
                src["final_score"] = round(item.final_score, 4)
            sources.append(src)
        return sources

    def _collect_conditions(self, items: list[RetrievedItem]) -> list[str]:
        """Collect all applicable conditions from retrieved items."""
        seen: set[str] = set()
        conditions = []
        for item in items:
            for cond in item.conditions:
                if cond and cond not in seen:
                    seen.add(cond)
                    conditions.append(cond)
        return conditions

    def _build_recommendations(self, items: list[RetrievedItem]) -> list[str]:
        """Generate actionable recommendations from results."""
        recs = []
        for item in items:
            if item.tier == Tier.JUDGMENTS and "never" in item.statement.lower():
                recs.append(f"Follow expert guidance: {item.statement[:100]}...")
            if item.conditions:
                for cond in item.conditions:
                    recs.append(f"Condition applies: {cond}")
        return recs[:3]

    def _determine_confidence(self, items: list[RetrievedItem]) -> str:
        """Determine confidence level based on source convergence."""
        if not items:
            return "low"
        tiers = {item.tier for item in items[:3]}
        if Tier.JUDGMENTS in tiers and Tier.FACTS in tiers:
            if len(items) >= 2:
                return "high"
        if len(items) >= 2:
            return "medium"
        return "low"

    def stats(self) -> dict[str, Any]:
        """Return server and index statistics."""
        return {
            "initialized": self._initialized,
            "chroma": self.chroma.stats(),
            "graph": self.graph.stats(),
            "cache_size": len(self._cache),
        }


# ─── MCP stdio protocol handlers ──────────────────────────────────────────

server = NumaRAGServer()


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    """Handle a single MCP request over stdin/stdout."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        server.initialize()
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": "numa-rag-server",
                    "version": "1.0.0",
                },
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "kgaa_search",
                        "description": "Hybrid knowledge search combining graph traversal and semantic vector search via Reciprocal Rank Fusion (RRF). Returns answers with source attribution and confidence scoring.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Natural language query about the knowledge domain",
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": "Maximum number of sources to return (default: 5)",
                                    "default": 5,
                                },
                            },
                            "required": ["query"],
                        },
                    }
                ]
            },
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "kgaa_search":
            query = arguments.get("query", "")
            limit = min(int(arguments.get("limit", 5)), 20)
            result = server.kgaa_search(query, limit)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2, ensure_ascii=False),
                        }
                    ],
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
        }

    if method == "numa/stats":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": server.stats(),
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    """Run the MCP server over stdio."""
    import sys

    logger.info("NUMA RAG Server starting (MCP stdio)...")
    server.initialize()
    logger.info("Server ready. Waiting for requests on stdin...")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON: %s", exc)
        except Exception as exc:
            logger.exception("Error handling request: %s", exc)
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(exc)},
            }
            sys.stdout.write(json.dumps(error_response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
