"""NUMA Benchmark — retrieval mode definitions and query simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from numa_bench.questions import BenchmarkQuestion


@dataclass
class RetrievalMode:
    """Configuration for a retrieval mode."""

    name: str
    description: str
    tool_calls: int
    token_cost: float  # average tokens per query
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


def simulate_query(
    mode: RetrievalMode, question: BenchmarkQuestion
) -> QueryResult:
    """Simulate a single benchmark query run.

    In a real run this would call the actual retrieval pipeline.
    For offline use, returns expected benchmark values from the paper.
    """
    if mode.name == "Traditional":
        token_cost = mode.token_cost
        overlap = 100.0  # Traditional is the baseline
    elif mode.name == "Graph-Only":
        token_cost = mode.token_cost
        overlap = 0.0  # No semantic context
    elif mode.name == "KGAA":
        token_cost = mode.token_cost
        overlap = 50.0  # Partial
    else:  # KGAA+RRF
        token_cost = mode.token_cost
        overlap = 67.0

    return QueryResult(
        question_id=question.id,
        mode=mode.name,
        tokens=token_cost,
        calls=mode.tool_calls,
        keyword_overlap=overlap,
        answer=f"Simulated response for {question.id} using {mode.name} mode",
    )
