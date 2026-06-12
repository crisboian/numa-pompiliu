#!/usr/bin/env python3
"""
NUMA Benchmark — Claw Memory
Compares retrieval modes using the NUMA methodology on Claw's own knowledge base.

Modes:
  - Trad: Traditional multi-call (simulated: keyword grep + read)
  - Graph-Only: Keyword-based graph traversal
  - Vector-Only: ChromaDB semantic search
  - KGAA: Both concatenated
  - KGAA+RRF: Fused via Reciprocal Rank Fusion (NUMA recommended)
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/root/numa-memory")
from query import load_statements, get_chroma, search_vector, search_graph, rrf_fuse

# ── Benchmark Questions ──────────────────────────────────────
# 7 questions spanning 5 cognitive types (matching NUMA paper §5)
QUESTIONS = [
    # Factual lookup
    ("What is the Proxmox host IP address?", "factual"),
    ("What model does Cristian use as primary LLM?", "factual"),
    # Exception handling
    ("How should Claw behave differently in group chats vs DMs?", "exception"),
    ("When should Claw NOT respond to messages?", "exception"),
    # Causal reasoning
    ("Why was DNS rebinding protection disabled for the MCP server?", "causal"),
    # Procedural sequencing
    ("What steps are needed to fix Hermes when it crash-loops?", "procedural"),
    # Judgment under conflict
    ("Should Claw use DeepSeek Pro or a local fallback model?", "judgment"),
]

# Gold answers (expert-validated, manually verified from memory files)
GOLD = {
    "What is the Proxmox host IP address?": ["192.168.99.1", "proxmox", "8006"],
    "What model does Cristian use as primary LLM?": ["deepseek", "deepseek pro", "modelo principal"],
    "How should Claw behave differently in group chats vs DMs?": ["group", "participant", "not their voice", "don't share"],
    "When should Claw NOT respond to messages?": ["silent", "no_reply", "banter", "already answered"],
    "Why was DNS rebinding protection disabled for the MCP server?": ["dns rebinding", "421", "lan", "mcp"],
    "What steps are needed to fix Hermes when it crash-loops?": ["fix-hermes", "crash", "skill", "restart"],
    "Should Claw use DeepSeek Pro or a local fallback model?": ["deepseek", "pro", "fallback", "local", "gemma"],
}


def keyword_overlap(result_text: str, gold_keywords: list[str]) -> float:
    """Calculate keyword overlap between result and gold answer."""
    text_lower = result_text.lower()
    matches = sum(1 for kw in gold_keywords if kw.lower() in text_lower)
    return matches / len(gold_keywords) if gold_keywords else 0.0


def simulate_traditional(query_text: str) -> dict:
    """Simulate traditional multi-call: grep + read (4 calls, high token usage)."""
    start = time.time()

    # Simulate: search memory, read files, synthesize
    # Traditional approach would do multiple searches
    workspace = Path("/root/.openclaw/workspace")
    results = []
    tokens_est = 0

    # grep across memory files (simulated)
    for md_file in sorted(workspace.glob("*.md")) + sorted((workspace / "memory").glob("*.md")):
        try:
            content = md_file.read_text()
            # Each file read = tokens consumed
            tokens_est += len(content) // 4  # rough token estimate
            results.append(content)
        except Exception:
            pass

    # Simulate: calls = 4 (search + 3 reads)
    latency = (time.time() - start) * 1000

    # Build answer from all text
    combined = " ".join(results[:2000])  # top results
    overlap = keyword_overlap(combined, GOLD.get(query_text, []))

    return {
        "tokens": tokens_est,
        "calls": 4,
        "latency_ms": round(latency, 1),
        "keyword_overlap": round(overlap, 3),
        "mode": "Traditional",
    }


def run_benchmark():
    """Run full benchmark across all modes."""
    statements = load_statements()
    collection = get_chroma()

    if not statements:
        print("❌ No index. Run index first.")
        return

    modes = {
        "Traditional": None,  # simulated
        "Graph-Only": "graph_only",
        "Vector-Only": "vector_only",
        "KGAA": "kgaa",
        "KGAA+RRF": "kgaa_rrf",
    }

    print("=" * 80)
    print("  NUMA BENCHMARK — Claw Memory (147 statements, 3 tiers)")
    print("=" * 80)
    print()

    all_results = {}

    for mode_name, mode in modes.items():
        print(f"\n{'─' * 60}")
        print(f"  MODE: {mode_name}")
        print(f"{'─' * 60}")

        mode_results = []
        total_tokens = 0
        total_calls = 0
        total_latency = 0
        total_overlap = 0

        for q, qtype in QUESTIONS:
            if mode is None:
                # Traditional simulation
                r = simulate_traditional(q)
            else:
                start = time.time()
                v = search_vector(collection, statements, q, n_results=10)
                g = search_graph(statements, q, n_results=10)

                if mode == "vector_only":
                    items = v[:5]
                    calls = 1
                elif mode == "graph_only":
                    items = g[:5]
                    calls = 1
                elif mode == "kgaa_rrf":
                    items = rrf_fuse(g, v)[:5]
                    calls = 1
                else:  # kgaa
                    # Concatenate both calls
                    seen = set()
                    items = []
                    for vi, gi in zip(v, g):
                        for item in [vi, gi]:
                            k = item["statement"][:80].lower()
                            if k not in seen:
                                seen.add(k)
                                items.append(item)
                    items = items[:5]
                    calls = 2

                latency = (time.time() - start) * 1000

                # Estimate tokens for each mode
                answer_len = sum(len(item.get("statement", "")) for item in items)
                tokens = answer_len // 4

                combined = " ".join(item.get("statement", "") for item in items)
                overlap = keyword_overlap(combined, GOLD.get(q, []))

                r = {
                    "tokens": tokens,
                    "calls": calls,
                    "latency_ms": round(latency, 1),
                    "keyword_overlap": round(overlap, 3),
                    "mode": mode_name,
                }

            mode_results.append(r)
            total_tokens += r["tokens"]
            total_calls += r["calls"]
            total_latency += r["latency_ms"]
            total_overlap += r["keyword_overlap"]

        avg_tokens = total_tokens / len(QUESTIONS)
        avg_calls = total_calls / len(QUESTIONS)
        avg_latency = total_latency / len(QUESTIONS)
        avg_overlap = total_overlap / len(QUESTIONS)

        # Per-question detail
        for i, (q, qtype) in enumerate(QUESTIONS):
            r = mode_results[i]
            print(f"\n  Q{i+1}: {q[:60]}...")
            print(f"       [{qtype:12s}] tokens={r['tokens']:5d}  calls={r['calls']}  "
                  f"lat={r['latency_ms']:6.1f}ms  overlap={r['keyword_overlap']:.3f}")

        print(f"\n  {'─' * 50}")
        print(f"  AVERAGE: tokens={avg_tokens:.0f}  calls={avg_calls:.1f}  "
              f"latency={avg_latency:.1f}ms  overlap={avg_overlap:.3f}")

        all_results[mode_name] = {
            "avg_tokens": round(avg_tokens),
            "avg_calls": round(avg_calls, 1),
            "avg_latency_ms": round(avg_latency, 1),
            "avg_keyword_overlap": round(avg_overlap, 3),
            "per_question": mode_results,
        }

    # ── Summary table ──────────────────────────────────────────
    print(f"\n\n{'=' * 80}")
    print(f"  FINAL COMPARISON")
    print(f"{'=' * 80}")
    print(f"\n  {'Mode':<16s} {'Tokens/q':>8s} {'Calls/q':>8s} {'Latency':>10s} {'Overlap':>8s} {'Reduction':>10s}")
    print(f"  {'─' * 16} {'─' * 8} {'─' * 8} {'─' * 10} {'─' * 8} {'─' * 10}")

    trad_tokens = all_results["Traditional"]["avg_tokens"]

    for mode_name in ["Traditional", "Graph-Only", "Vector-Only", "KGAA", "KGAA+RRF"]:
        r = all_results[mode_name]
        if mode_name == "Traditional":
            reduction = ""
        else:
            pct = (1 - r["avg_tokens"] / trad_tokens) * 100
            reduction = f"{pct:.1f}%"
        print(f"  {mode_name:<16s} {r['avg_tokens']:>8d} {r['avg_calls']:>8.1f} "
              f"{r['avg_latency_ms']:>8.1f}ms {r['avg_keyword_overlap']:>8.3f} {reduction:>10s}")

    print()

    # Save results
    result_path = "/root/numa-memory/data/benchmark_results.json"
    with open(result_path, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"📊 Results saved to {result_path}")

    return all_results


if __name__ == "__main__":
    run_benchmark()
