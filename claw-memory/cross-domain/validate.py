#!/usr/bin/env python3
"""
NUMA Cross-Domain Validation — Industrial Safety & Occupational Risk
Validates domain-agnosticism claim from NUMA paper §5.2.
Domain: Prensa hidráulica K-700 (manufacturing safety)

Compares results against code-domain benchmark for transferability evidence.
"""

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/root/numa-memory")
from query import load_statements, get_chroma, search_vector, search_graph, rrf_fuse

# ── Standalone indexer for cross-domain corpus ──────────────────
sys.path.insert(0, "/root/numa-memory")
from claw_memory import ClawKnowledgeIndexer, ClawMemoryStore, KnowledgeStatement

CROSS_CORPUS = Path("/root/numa-memory/cross_domain/corpus")
CROSS_STORE_PATH = "/root/numa-memory/cross_domain/data"

# Cross-domain file → tier mapping
CROSS_TIER_MAP = {
    "01-manual-k700.md": "facts",           # Manual, SOPs
    "02-incidentes-k700.md": "facts",        # Incident records
    "03-normativa-prl.md": "facts",          # Regulations
    "04-entrevista-pepe-garcia.md": "judgments",  # Expert interview
}

# ── Gold answers (expert-validated from Pepe García interview) ──
CROSS_GOLD = {
    "What is the maximum safe operating temperature for the K-700?": {
        "keywords": ["185", "185°C", "never exceed", "junta", "junta derecha", "depósito"],
        "answer": "Never exceed 185°C at the tank indicator, even though the manual says 190°C. The right-hand gasket runs 30-40°C hotter than the tank.",
    },
    "Why was the thermostat set to 180°C instead of the NTP-recommended 200°C?": {
        "keywords": ["junta", "gasket", "fundir", "melt", "190", "190°C", "incendio", "fire", "protection"],
        "answer": "The NTP protects against oil fires (ignition point 220°C), not gasket failure. The gasket melts at 190°C real temperature, so 200°C would be too late.",
    },
    "What should you do when starting the K-700 on a cold Monday morning?": {
        "keywords": ["300", "segundos", "minutes", "invierno", "winter", "frío", "cold", "cavitación", "cavitation", "viscosidad", "viscosity"],
        "answer": "Wait 300 seconds instead of 120s. At 2-4°C, ISO VG 46 oil has triple the viscosity, so the pump needs more time to avoid cavitation.",
    },
    "What oil does the K-700 actually need in winter?": {
        "keywords": ["vg 32", "mezclar", "mix", "30%", "invierno", "winter", "viscosidad", "bomba", "pump"],
        "answer": "Mix 70% VG 46 with 30% VG 32 from November to March. This is unofficial but extends pump life by 60%.",
    },
    "How often should the right-hand gasket (K7-GR-0034) be replaced?": {
        "keywords": ["6 meses", "months", "semestral", "derecha", "right", "cada 6", "biannual", "every 6"],
        "answer": "Every 6 months, not annually as the manual states. The right gasket degrades twice as fast due to proximity to the heating coil.",
    },
    "What was the root cause of the 2019 incident (#234)?": {
        "keywords": ["termostato", "thermostat", "200°C", "calibrado", "calibrated", "factory", "fábrica", "error", "193°C"],
        "answer": "The safety thermostat was miscalibrated from factory at 200°C instead of 180°C. Oil reached 193°C, right gasket melted, causing an oil leak and near-fire.",
    },
    "At what tank temperature should you stop production to prevent gasket failure?": {
        "keywords": ["55°C", "55", "parar", "stop", "producción", "production", "exponencial", "exponential"],
        "answer": "Stop production at 55°C tank indicator. At this point the right gasket is already at ~190°C and degradation accelerates exponentially.",
    },
}


def keyword_overlap(text: str, keywords: list[str]) -> float:
    """Calculate keyword overlap ratio."""
    text_lower = text.lower()
    matches = sum(1 for kw in keywords if kw.lower() in text_lower)
    return matches / len(keywords) if keywords else 0.0


def index_cross_domain_corpus():
    """Index the cross-domain industrial safety corpus into ChromaDB."""
    print("📚 Indexing cross-domain corpus (Industrial Safety)...")

    # Use a custom indexer for cross-domain files
    store = ClawMemoryStore(persist_dir=CROSS_STORE_PATH)
    statements = []

    for filename, default_tier in CROSS_TIER_MAP.items():
        filepath = CROSS_CORPUS / filename
        if not filepath.exists():
            print(f"  ⚠️ Missing: {filepath}")
            continue

        content = filepath.read_text()

        if filename == "04-entrevista-pepe-garcia.md":
            # Special handling: split interview into phases and statements
            # Extract Q&A pairs and knowledge statements
            phases = content.split("## Fase")
            for phase in phases[1:]:  # Skip header
                # Split into logical paragraphs
                paragraphs = [p.strip() for p in phase.split("\n\n") if p.strip() and len(p.strip()) > 80]
                for para in paragraphs[:10]:  # Take first 10 substantial paragraphs per phase
                    tier = "judgments" if "**" in para[:20] else "intuitions"
                    if "Creo" in para or "intuición" in para.lower():
                        tier = "intuitions"
                    ks = KnowledgeStatement(
                        statement=para[:800],
                        tier=tier,
                        source=f"{filename} → {phase.split(chr(10))[0].strip()[:60]}",
                        expert_name="Pepe García",
                        confidence=0.9,
                    )
                    statements.append(ks)
        else:
            # Facts documents: split by sections
            sections = content.split("## ")
            for section in sections[1:]:
                lines = section.strip().split("\n")
                header = lines[0].strip() if lines else ""
                body = "\n".join(lines[1:]).strip()

                if len(body) > 50:
                    ks = KnowledgeStatement(
                        statement=f"{header}: {body[:700]}",
                        tier=default_tier,
                        source=f"{filename} → {header[:60]}",
                        confidence=1.0 if default_tier == "facts" else 0.85,
                    )
                    statements.append(ks)

    store.index_statements(statements)

    tiers = defaultdict(int)
    for s in statements:
        tiers[s.tier] += 1
    print(f"✅ Cross-domain: {len(statements)} statements "
          f"(Facts:{tiers['facts']} Judgments:{tiers['judgments']} Intuitions:{tiers['intuitions']})")

    return statements


def run_cross_domain_benchmark():
    """Run full cross-domain benchmark across all retrieval modes."""

    # Index if needed
    cache_path = Path(CROSS_STORE_PATH) / "statements_cache.json"
    if not cache_path.exists():
        index_cross_domain_corpus()

    # Load cross-domain ChromaDB directly
    statements_path = Path(CROSS_STORE_PATH) / "statements_cache.json"
    with open(str(statements_path)) as f:
        statements = json.load(f)

    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(
        path=str(Path(CROSS_STORE_PATH) / "chroma"),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_collection("claw_knowledge")

    print(f"\n{'='*80}")
    print(f"  NUMA CROSS-DOMAIN BENCHMARK")
    print(f"  Domain: Industrial Safety — K-700 Hydraulic Press")
    print(f"  Corpus: {len(statements)} statements | Manuals + Incidents + Regulations + Expert Interview")
    print(f"{'='*80}")

    questions = list(CROSS_GOLD.keys())

    # Traditional baseline: read all files
    print(f"\n{'─'*60}")
    print(f"  MODE: Traditional (read all files)")
    print(f"{'─'*60}")
    trad_tokens = 0
    trad_overlap = 0
    for filename in CROSS_TIER_MAP:
        content = (CROSS_CORPUS / filename).read_text()
        trad_tokens += len(content) // 4
        trad_overlap_local = 0
        for q in questions:
            trad_overlap_local += keyword_overlap(content, CROSS_GOLD[q]["keywords"])
        trad_overlap += trad_overlap_local / len(questions)
    trad_tokens_per_q = trad_tokens  # Read all for each query
    trad_overlap_avg = trad_overlap / len(CROSS_TIER_MAP)
    print(f"  Tokens/q: {trad_tokens_per_q} | Calls: 4 | Overlap: {trad_overlap_avg:.3f}")

    # NUMA modes
    modes = {
        "Graph-Only": "graph",
        "Vector-Only": "vector",
        "KGAA": "kgaa",
        "KGAA+RRF": "kgaa_rrf",
    }

    results = {"Traditional": {
        "tokens_per_q": trad_tokens_per_q,
        "calls_per_q": 4.0,
        "overlap": round(trad_overlap_avg, 3),
        "mode": "Traditional",
    }}

    for mode_name, mode_type in modes.items():
        print(f"\n{'─'*60}")
        print(f"  MODE: {mode_name}")
        print(f"{'─'*60}")

        total_tokens = 0
        total_calls = 0
        total_overlap = 0
        total_latency = 0

        for i, q in enumerate(questions):
            start = time.time()

            v = search_vector(collection, statements, q, n_results=10)
            g = search_graph(statements, q, n_results=10)

            if mode_type == "vector":
                items = v[:5]
                calls = 1
            elif mode_type == "graph":
                items = g[:5]
                calls = 1
            elif mode_type == "kgaa_rrf":
                items = rrf_fuse(g, v)[:5]
                calls = 1
            else:  # kgaa
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
            answer_len = sum(len(item.get("statement", "")) for item in items)
            tokens = answer_len // 4
            combined = " ".join(item.get("statement", "") for item in items)
            gold_kw = CROSS_GOLD[q]["keywords"]
            overlap = keyword_overlap(combined, gold_kw)

            total_tokens += tokens
            total_calls += calls
            total_overlap += overlap
            total_latency += latency

            qtype_map = {
                0: "factual", 1: "causal", 2: "exception",
                3: "procedural", 4: "judgment", 5: "causal", 6: "judgment"
            }
            qtype = qtype_map.get(i, "factual")

            print(f"\n  Q{i+1}: {q[:70]}...")
            print(f"       [{qtype:12s}] tokens={tokens:5d}  calls={calls}  "
                  f"lat={latency:6.1f}ms  overlap={overlap:.3f}")
            if items:
                top = items[0].get("statement", "")[:120]
                print(f"       Top: {top}...")

        avg_tokens = total_tokens / len(questions)
        avg_calls = total_calls / len(questions)
        avg_overlap = total_overlap / len(questions)
        avg_latency = total_latency / len(questions)

        print(f"\n  {'─'*50}")
        print(f"  AVERAGE: tokens={avg_tokens:.0f}  calls={avg_calls:.1f}  "
              f"latency={avg_latency:.1f}ms  overlap={avg_overlap:.3f}")

        results[mode_name] = {
            "tokens_per_q": round(avg_tokens),
            "calls_per_q": round(avg_calls, 1),
            "latency_ms": round(avg_latency, 1),
            "overlap": round(avg_overlap, 3),
            "mode": mode_name,
        }

    # ── FINAL COMPARISON TABLE ──────────────────────────────────
    print(f"\n\n{'='*80}")
    print(f"  CROSS-DOMAIN VALIDATION — Industrial Safety vs Code Domain")
    print(f"{'='*80}")
    print(f"\n  {'Mode':<16s} {'Tokens/q':>8s} {'Calls/q':>8s} {'Overlap':>8s} {'vs Code':>10s}")
    print(f"  {'─'*16} {'─'*8} {'─'*8} {'─'*8} {'─'*10}")

    # Code domain results (from our earlier benchmark)
    code_results = {
        "Traditional": {"tokens_per_q": 6281, "overlap": 0.845},
        "Graph-Only": {"tokens_per_q": 564, "overlap": 0.810},
        "Vector-Only": {"tokens_per_q": 213, "overlap": 0.526},
        "KGAA": {"tokens_per_q": 387, "overlap": 0.691},
        "KGAA+RRF": {"tokens_per_q": 574, "overlap": 0.569},
    }

    for mode_name in ["Traditional", "Graph-Only", "Vector-Only", "KGAA", "KGAA+RRF"]:
        r = results[mode_name]
        cr = code_results.get(mode_name, {})
        reduction = ""
        if mode_name != "Traditional":
            pct = (1 - r["tokens_per_q"] / results["Traditional"]["tokens_per_q"]) * 100
            reduction = f"{pct:.1f}%"
        code_overlap = cr.get("overlap", "-")
        code_tokens = cr.get("tokens_per_q", "-")
        print(f"  {mode_name:<16s} {r['tokens_per_q']:>8d} {r['calls_per_q']:>8.1f} "
              f"{r['overlap']:>8.3f} {reduction:>10s}")

    # Save results
    out_path = "/root/numa-memory/cross_domain/benchmark_results.json"
    with open(out_path, "w") as f:
        json.dump({"cross_domain": results, "code_domain": code_results}, f, indent=2, ensure_ascii=False)
    print(f"\n📊 Results saved to {out_path}")

    return results


if __name__ == "__main__":
    run_cross_domain_benchmark()
