"""NUMA Benchmark runner — executes 7 questions × 4 modes."""

from __future__ import annotations

import sys
import time

from numa_bench.metrics import compute_metrics
from numa_bench.modes import MODES, QueryResult, simulate_query
from numa_bench.questions import QUESTIONS
from numa_bench.report import format_summary


def run_benchmark() -> list[QueryResult]:
    """Run all 7 questions across all 4 retrieval modes.

    Returns 28 QueryResult objects (7 × 4).
    """
    results: list[QueryResult] = []
    total = len(QUESTIONS) * len(MODES)

    print(f"🚀 Running NUMA Benchmark: {len(QUESTIONS)} questions × {len(MODES)} modes = {total} runs")
    print()

    for mode in MODES:
        print(f"  Mode: {mode.name} ({mode.description})")
        for question in QUESTIONS:
            start = time.time()
            result = simulate_query(mode, question)
            result.latency_ms = (time.time() - start) * 1000
            results.append(result)
            print(f"    ✓ {question.id} ({question.cognitive_type}) — {result.tokens}tok, {result.calls}calls")
        print()

    return results


def main() -> None:
    """Entry point: run benchmark and print report."""
    results = run_benchmark()
    metrics = compute_metrics(results)
    report = format_summary(metrics)

    print()
    print("=" * 60)
    print("📊 BENCHMARK REPORT")
    print("=" * 60)
    print()
    print(report)


if __name__ == "__main__":
    main()
