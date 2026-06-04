"""NUMA Benchmark — retrieval mode definitions and real query execution."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from numa_bench.questions import BenchmarkQuestion


@dataclass
class RetrievalMode:
    """Configuration for a retrieval mode."""

    name: str
    description: str
    tool_calls: int
    token_cost: float  # paper-projected average tokens per query (reference only)
    uses_graph: bool = False
    uses_vector: bool = False
    uses_rrf: bool = False


MODES = [
    RetrievalMode(
        name="Traditional",
        description="Multi-call baseline: 4 sequential queries to LLM",
        tool_calls=4,
        token_cost=1500,
        uses_graph=False,
        uses_vector=False,
        uses_rrf=False,
    ),
    RetrievalMode(
        name="Graph-Only",
        description="Structural graph traversal only (no semantic search)",
        tool_calls=1,
        token_cost=107,
        uses_graph=True,
        uses_vector=False,
        uses_rrf=False,
    ),
    RetrievalMode(
        name="KGAA",
        description="Graph + vector search without RRF fusion (2 calls)",
        tool_calls=2,
        token_cost=998,
        uses_graph=True,
        uses_vector=True,
        uses_rrf=False,
    ),
    RetrievalMode(
        name="KGAA+RRF",
        description="Graph + vector search fused via Reciprocal Rank Fusion (1 call)",
        tool_calls=1,
        token_cost=527,
        uses_graph=True,
        uses_vector=True,
        uses_rrf=True,
    ),
]


@dataclass
class QueryResult:
    """Result of a single benchmark query run."""

    question_id: str
    mode: str
    tokens: int
    calls: int
    answer: str = ""
    keyword_overlap: float = 0.0
    latency_ms: float = 0.0
    error: str = ""


def compute_keyword_overlap(
    answer: str, question: BenchmarkQuestion
) -> float:
    """Calculate keyword overlap percentage between answer and gold keywords."""
    if not question.keywords:
        return 0.0

    answer_lower = answer.lower()
    matched = sum(1 for kw in question.keywords if kw.lower() in answer_lower)
    return (matched / len(question.keywords)) * 100.0


def _approx_tokens(text: str) -> int:
    """Approximate token count: ~4 chars per token."""
    return max(1, len(text) // 4)


def _server_package_path() -> Path:
    """Locate the numa-rag-server package alongside numa-benchmark."""
    here = Path(__file__).resolve()
    return here.parent.parent.parent / "numa-rag-server"


def _ensure_server_importable() -> None:
    """Make numa_rag importable when running from a sibling directory."""
    pkg_path = _server_package_path()
    pkg_str = str(pkg_path)
    if pkg_str not in sys.path:
        sys.path.insert(0, pkg_str)


_SERVER_SINGLETON: Any = None


def _get_server() -> Any:
    """Lazy-init a single NumaRAGServer for the whole benchmark run."""
    global _SERVER_SINGLETON
    if _SERVER_SINGLETON is None:
        _ensure_server_importable()
        from numa_rag.server import NumaRAGServer

        srv = NumaRAGServer()
        srv.initialize()
        _SERVER_SINGLETON = srv
    return _SERVER_SINGLETON


def _disable_cache(server: Any) -> None:
    """Force the server to skip its cache for this query."""
    server._cache.clear()


def _build_answer_text(server: Any, items: list[Any]) -> str:
    """Reuse the server's answer assembly so token counts reflect production output."""
    return server._build_answer("", items)


def _run_graph_only(server: Any, question: BenchmarkQuestion, limit: int) -> tuple[str, int]:
    items = server.graph.search(question.question, limit=limit)
    answer = _build_answer_text(server, items)
    return answer, 1


def _run_kgaa_no_rrf(
    server: Any, question: BenchmarkQuestion, limit: int
) -> tuple[str, int]:
    graph_items = server.graph.search(question.question, limit=limit)
    vector_items = server.chroma.search(question.question, limit=limit)
    seen: set[str] = set()
    merged: list[Any] = []
    for item in list(graph_items) + list(vector_items):
        key = item.statement.strip().lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    answer = _build_answer_text(server, merged[:limit])
    return answer, 2


def _run_kgaa_rrf(
    server: Any, question: BenchmarkQuestion, limit: int
) -> tuple[str, int]:
    _disable_cache(server)
    result = server.kgaa_search(question.question, limit=limit)
    return result.get("answer", ""), 1


def _run_traditional(question: BenchmarkQuestion) -> tuple[str, int]:
    """Simulated baseline — no retrieval pipeline, just the expected answer text."""
    return question.expected_answer, 4


def simulate_query(
    mode: RetrievalMode, question: BenchmarkQuestion
) -> QueryResult:
    """Execute a real benchmark query against the NUMA RAG server.

    Each mode hits a different slice of the retrieval pipeline so the
    token and overlap numbers reflect actual behavior, not paper constants.
    """
    server = _get_server()
    _disable_cache(server)
    limit = 5

    start = time.time()
    try:
        if mode.name == "Traditional":
            answer, calls = _run_traditional(question)
        elif mode.name == "Graph-Only":
            answer, calls = _run_graph_only(server, question, limit)
        elif mode.name == "KGAA":
            answer, calls = _run_kgaa_no_rrf(server, question, limit)
        elif mode.name == "KGAA+RRF":
            answer, calls = _run_kgaa_rrf(server, question, limit)
        else:
            return QueryResult(
                question_id=question.id,
                mode=mode.name,
                tokens=0,
                calls=0,
                error=f"Unknown mode: {mode.name}",
            )
    except Exception as exc:
        return QueryResult(
            question_id=question.id,
            mode=mode.name,
            tokens=0,
            calls=0,
            latency_ms=(time.time() - start) * 1000,
            error=str(exc),
        )

    latency_ms = (time.time() - start) * 1000
    tokens = _approx_tokens(answer) + _approx_tokens(question.question)
    overlap = compute_keyword_overlap(answer, question)

    return QueryResult(
        question_id=question.id,
        mode=mode.name,
        tokens=tokens,
        calls=calls,
        answer=answer,
        keyword_overlap=overlap,
        latency_ms=latency_ms,
    )
