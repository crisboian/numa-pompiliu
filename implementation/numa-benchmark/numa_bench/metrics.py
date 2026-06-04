"""NUMA Benchmark — metrics calculation and tabulation."""

from __future__ import annotations

from statistics import mean
from typing import Sequence

from numa_bench.modes import MODES, QueryResult


class BenchmarkMetrics:
    """Aggregated benchmark metrics for a retrieval mode."""

    def __init__(self, mode_name: str) -> None:
        self.mode_name = mode_name
        self.query_results: list[QueryResult] = []

    def add(self, result: QueryResult) -> None:
        """Add a single query result."""
        self.query_results.append(result)

    @property
    def avg_tokens(self) -> float:
        if not self.query_results:
            return 0.0
        return mean(r.tokens for r in self.query_results)

    @property
    def avg_calls(self) -> float:
        if not self.query_results:
            return 0.0
        return mean(r.calls for r in self.query_results)

    @property
    def avg_keyword_overlap(self) -> float:
        if not self.query_results:
            return 0.0
        return mean(r.keyword_overlap for r in self.query_results)

    @property
    def total_tokens(self) -> int:
        return sum(r.tokens for r in self.query_results)

    @property
    def total_calls(self) -> int:
        return sum(r.calls for r in self.query_results)


def compute_metrics(
    results: list[QueryResult],
) -> dict[str, BenchmarkMetrics]:
    """Group results by mode and compute per-mode metrics."""
    by_mode: dict[str, list[QueryResult]] = {}
    for r in results:
        by_mode.setdefault(r.mode, []).append(r)

    metrics = {}
    for mode_name, mode_results in by_mode.items():
        m = BenchmarkMetrics(mode_name)
        for r in mode_results:
            m.add(r)
        metrics[mode_name] = m

    return metrics


def compute_reductions(
    metrics: dict[str, BenchmarkMetrics], baseline_name: str = "Traditional"
) -> dict[str, dict[str, float]]:
    """Compute token and call reductions relative to baseline."""
    baseline = metrics.get(baseline_name)
    if not baseline:
        return {}

    reductions = {}
    for name, m in metrics.items():
        if name == baseline_name:
            continue
        token_reduction = (
            (baseline.avg_tokens - m.avg_tokens) / baseline.avg_tokens * 100
        )
        call_reduction = (
            (baseline.avg_calls - m.avg_calls) / baseline.avg_calls * 100
        )
        reductions[name] = {
            "token_reduction_pct": round(token_reduction, 1),
            "call_reduction_pct": round(call_reduction, 1),
        }

    return reductions
