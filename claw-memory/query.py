#!/usr/bin/env python3
"""
NUMA Memory for Claw — Fast Query Edition
Loads pre-indexed ChromaDB + statement cache. No re-index on each query.

Usage:
  python3 query.py "what is the proxmox ip"
  python3 query.py "how does claw behave in groups" --json
"""

import json
import os
import sys
import time
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

# ── Data dir ──────────────────────────────────────────────────
DATA_DIR = Path("/root/numa-memory/data")
CACHE_PATH = DATA_DIR / "statements_cache.json"

TIER_WEIGHTS = {"facts": 0.3, "judgments": 0.7, "intuitions": 0.5}
K_SMOOTHING = 60


def load_statements():
    """Load cached statements from JSON."""
    if not CACHE_PATH.exists():
        return None
    with open(CACHE_PATH) as f:
        return json.load(f)


def get_chroma():
    """Get ChromaDB client and collection."""
    client = chromadb.PersistentClient(
        path=str(DATA_DIR / "chroma"),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    try:
        return client.get_collection("claw_knowledge")
    except Exception:
        return None


def search_vector(collection, statements, query: str, n_results: int = 10):
    """Vector search via ChromaDB."""
    if not collection or not statements:
        return []
    results = collection.query(query_texts=[query], n_results=min(n_results, len(statements)))
    items = []
    stmt_by_id = {s["id"]: s for s in statements}
    if results.get("ids") and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            ks = stmt_by_id.get(doc_id)
            if not ks:
                continue
            dist = results.get("distances", [[1.0]])
            d = dist[0][i] if dist and len(dist) > 0 and len(dist[0]) > i else 1.0
            score = 1.0 / (1.0 + d)
            items.append({
                "statement": ks["statement"],
                "tier": ks["tier"],
                "weight": ks["weight"],
                "source": ks["source"],
                "vector_score": score,
                "vector_rank": i + 1,
            })
    return items


def search_graph(statements, query: str, n_results: int = 10):
    """Keyword-based graph-style search."""
    if not statements:
        return []
    query_terms = set(query.lower().split())
    if not query_terms:
        return []
    scored = []
    for ks in statements:
        stmt_lower = ks["statement"].lower()
        src_lower = ks["source"].lower()
        matches = sum(1 for t in query_terms if t in stmt_lower)
        if matches == 0:
            continue
        bonus = 2.0 if any(t in src_lower for t in query_terms) else 1.0
        score = (matches / len(query_terms)) * bonus
        scored.append({
            "statement": ks["statement"],
            "tier": ks["tier"],
            "weight": ks["weight"],
            "source": ks["source"],
            "graph_score": score,
            "graph_rank": 0,
        })
    scored.sort(key=lambda x: x["graph_score"], reverse=True)
    for i, item in enumerate(scored):
        item["graph_rank"] = i + 1
    return scored[:n_results]


def rrf_fuse(graph_items, vector_items, k=K_SMOOTHING):
    """RRF fusion of graph and vector results."""
    scores = {}
    items_by_key = {}

    def key(item):
        return item["statement"].strip()[:80].lower()

    for item in graph_items:
        k_ = key(item)
        scores[k_] = scores.get(k_, 0) + 1.0 / (k + item["graph_rank"])
        items_by_key[k_] = item

    for item in vector_items:
        k_ = key(item)
        scores[k_] = scores.get(k_, 0) + 1.0 / (k + item["vector_rank"])
        if k_ not in items_by_key:
            items_by_key[k_] = item

    result = []
    for k_, item in items_by_key.items():
        rrf = scores[k_]
        item["rrf_score"] = round(rrf, 6)
        item["final_score"] = round(rrf * item["weight"], 6)
        result.append(item)

    result.sort(key=lambda x: x["final_score"], reverse=True)
    return result


def query(query_text: str, top_n: int = 5):
    """Execute a fast NUMA knowledge query."""
    start = time.time()
    statements = load_statements()
    collection = get_chroma()

    if not statements:
        return {"error": "No index. Run: python3 claw_memory.py --index"}

    v = search_vector(collection, statements, query_text, n_results=10)
    g = search_graph(statements, query_text, n_results=10)
    fused = rrf_fuse(g, v)
    latency = (time.time() - start) * 1000

    return {
        "query": query_text,
        "latency_ms": round(latency, 1),
        "total_statements": len(statements),
        "results": fused[:top_n],
        "top_answer": fused[0]["statement"][:500] if fused else "No results.",
    }


def format_result(result: dict) -> str:
    """Format a query result for display."""
    if "error" in result:
        return f"❌ {result['error']}"

    lines = [
        f"🔍 **{result['query']}**",
        f"📊 {result['results_count'] if 'results_count' in result else len(result['results'])} results | {result['latency_ms']}ms | {result.get('total_statements', '?')} indexed",
        "",
    ]

    for i, r in enumerate(result["results"][:5]):
        tier_emoji = {"facts": "📋", "judgments": "🧠", "intuitions": "💡"}.get(r["tier"], "📄")
        lines.append(f"{i+1}. {tier_emoji} [{r['tier']}] (score={r.get('final_score', r.get('rrf_score', 0)):.4f})")
        lines.append(f"   📁 {r['source']}")
        lines.append(f"   {r['statement'][:200]}...")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NUMA Memory Fast Query")
    parser.add_argument("query", nargs="*", help="Search query")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--top", type=int, default=5)

    args = parser.parse_args()
    q = " ".join(args.query) if args.query else None

    if not q:
        # Show status
        stmts = load_statements()
        if stmts:
            tiers = {"facts": 0, "judgments": 0, "intuitions": 0}
            for s in stmts:
                tiers[s["tier"]] = tiers.get(s["tier"], 0) + 1
            print(f"🧠 NUMA Memory: {len(stmts)} statements indexed")
            print(f"   Facts: {tiers['facts']} | Judgments: {tiers['judgments']} | Intuitions: {tiers['intuitions']}")
            print(f"   ChromaDB: {'✅' if get_chroma() else '❌'}")
        else:
            print("❌ No index. Run: python3 /root/numa-memory/claw_memory.py --index")
    else:
        result = query(q, top_n=args.top)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(format_result(result))
