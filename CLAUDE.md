# Numa Pompiliu — Claude Code Context

## Architecture

- **Five protocols** in a lifecycle: Capture → Structure → Validation → Access → Maintenance
- **Knowledge tiers**: Facts (0.3), Judgments (0.7), Intuitions (0.5) — weights for retrieval scoring
- **Hybrid retrieval**: ChromaDB (semantic) + Graphify (graph) fused via RRF
- **MMemory**: Engram for session persistence
- **All MCP servers**: Provider-agnostic via Model Context Protocol

## Code Standards

- Python 3.11+, type hints on all public functions, Google-style docstrings
- Async where IO-bound (MCP server, ChromaDB calls)
- 4-space indentation, max line 100 chars
- Tests in `tests/` mirroring source structure

## Implementation Components

### numa-rag-server
- MCP server exposing `kgaa_search` tool
- Integrates ChromaDB (all-MiniLM-L6-v2, 384d), Graphify API, RRF fusion
- Cache layer for repeated queries
- `RRF(item) = Σ(1 / (k + rank_i(item)))` for i ∈ {graph, rag}, k=60

### numa-capture
- 4-phase interview orchestration:
  - Phase A (30min): Role mapping, concept graph, gap detection
  - Phase B (90min): Top 10 critical incidents with decision rationale
  - Phase C (60min): Inverse verification — challenge testimony against docs
  - Phase D (30min): "The Unwritten" — what appears in no document
- Output: Structured JSON with tiered knowledge (facts/judgments/intuitions)

### numa-benchmark
- 7 questions × 5 cognitive types × 4 retrieval modes
- Metrics: tokens/query, calls/query, reduction %, keyword overlap
- Modes: Traditional, Graph-Only, KGAA, KGAA+RRF

## Key Commands

```bash
# Run RAG server
python implementation/numa-rag-server/server.py

# Run benchmark
python implementation/numa-benchmark/run.py

# Run tests
python -m pytest tests/
```

## Domain Constraints

- Consumer hardware target (RTX A2000 8GB tested)
- Spanish/English bilingual support planned
- Single-expert capture (multi-expert triangulation is future work)
