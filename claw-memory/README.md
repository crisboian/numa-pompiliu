# Claw Memory — NUMA Implementation

NUMA protocol applied to Claw's persistent memory system.

## Structure

```
claw-memory/
├── claw_memory.py      # Full pipeline: indexer + ChromaDB + RRF
├── query.py            # Fast query (no re-index)
├── fact_extractor.py   # Atomic fact extraction (IPs, models, tokens, etc.)
├── benchmarks/
│   ├── benchmark.py               # Code-domain benchmark
│   ├── code_domain_results.json   # 147 statements, 5 modes
│   └── cross_domain_results.json  # Industrial safety validation
└── cross-domain/
    ├── validate.py                # Cross-domain benchmark runner
    └── corpus/                    # K-700 Industrial Safety corpus
        ├── 01-manual-k700.md
        ├── 02-incidentes-k700.md
        ├── 03-normativa-prl.md
        └── 04-entrevista-pepe-garcia.md
```

## Quick Start

```bash
# Index knowledge
python3 claw_memory.py --index

# Query
python3 query.py "proxmox host IP credentials"

# Benchmark (code domain)
python3 benchmarks/benchmark.py

# Cross-domain validation
python3 cross-domain/validate.py

# Status
python3 query.py
```

## Results

### Code Domain (Claw Memory · 147 statements)
| Mode | Tokens/q | Calls | Overlap |
|------|----------|-------|---------|
| Traditional | 6,281 | 4.0 | 0.845 |
| Graph-Only | 564 | 1.0 | 0.810 |
| **KGAA+RRF** | **574** | **1.0** | **0.569** |

### Cross-Domain (Industrial Safety · 35 statements)
| Mode | Tokens/q | Calls | Overlap |
|------|----------|-------|---------|
| Traditional | 3,588 | 4.0 | 0.310 |
| **KGAA+RRF** | **475** | **1.0** | **0.406** |

## Cron
Daily re-index at 03:00 CEST (Protocol 5: Maintenance)
