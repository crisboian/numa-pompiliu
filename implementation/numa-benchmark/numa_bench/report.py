"""NUMA Benchmark — results report generation."""

from __future__ import annotations

from numa_bench.metrics import BenchmarkMetrics, compute_reductions


def format_table(
    metrics: dict[str, BenchmarkMetrics],
    reductions: dict[str, dict[str, float]] | None = None,
) -> str:
    """Generate a markdown table of benchmark results.

    Matches the format from Table 3 in the NUMA paper.
    """
    if reductions is None:
        reductions = compute_reductions(metrics)

    lines = [
        "| Mode | Tokens/q | Calls/q | Reduction | Keyword overlap |",
        "|------|----------|---------|-----------|-----------------|",
    ]

    mode_order = ["Traditional", "Graph-Only", "KGAA", "KGAA+RRF"]
    for mode_name in mode_order:
        m = metrics.get(mode_name)
        if not m:
            continue

        tokens = f"{m.avg_tokens:.0f}"
        calls = f"{m.avg_calls:.1f}"

        red_data = reductions.get(mode_name, {})
        red_str = (
            f"{red_data['token_reduction_pct']:.1f}%"
            if red_data
            else "—"
        )

        overlap = f"{m.avg_keyword_overlap:.0f}%" if mode_name != "Traditional" else "—"

        lines.append(
            f"| {mode_name} | {tokens} | {calls} | {red_str} | {overlap} |"
        )

    return "\n".join(lines)


def format_summary(
    metrics: dict[str, BenchmarkMetrics],
) -> str:
    """Generate a detailed summary report."""
    reductions = compute_reductions(metrics)

    lines = [
        "# NUMA Benchmark Results",
        "",
        "## Retrieval Mode Comparison",
        "",
        format_table(metrics, reductions),
        "",
        "## Key Findings",
        "",
    ]

    kg_rrf = metrics.get("KGAA+RRF")
    traditional = metrics.get("Traditional")
    if kg_rrf and traditional:
        lines.extend(
            [
                f"- **KGAA+RRF** reduces token consumption by "
                f"{reductions.get('KGAA+RRF', {}).get('token_reduction_pct', 0):.1f}% "
                f"vs the Traditional multi-call baseline",
                f"- Collapses {traditional.avg_calls:.0f} tool calls into {kg_rrf.avg_calls:.0f} "
                f"({reductions.get('KGAA+RRF', {}).get('call_reduction_pct', 0):.1f}% reduction)",
                f"- Achieves {kg_rrf.avg_keyword_overlap:.0f}% keyword overlap with gold answers",
                "",
            ]
        )

    # Per-mode breakdown
    lines.append("## Per-Mode Breakdown")
    lines.append("")
    for mode_name in ["Traditional", "Graph-Only", "KGAA", "KGAA+RRF"]:
        m = metrics.get(mode_name)
        if not m:
            continue
        lines.extend(
            [
                f"### {mode_name}",
                f"- Total tokens: {m.total_tokens}",
                f"- Total calls: {m.total_calls}",
                f"- Average tokens/query: {m.avg_tokens:.0f}",
                f"- Average calls/query: {m.avg_calls:.1f}",
                "",
            ]
        )

    return "\n".join(lines)
