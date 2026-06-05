# Numa Pompiliu 🏛️

**Perpetuating expert knowledge through LLM-guided elicitation and graph-grounded retrieval.**

Numa is a complete, reproducible methodology for capturing, structuring, validating, accessing, and maintaining expert knowledge before it is lost to retirement.

Named after [Numa Pompilius](https://en.wikipedia.org/wiki/Numa_Pompilius) (753–673 BCE), the second king of Rome, who codified Rome's unwritten customs into durable institutions — demonstrating that codifying unwritten knowledge is among the most enduring contributions one can make.

## The Problem

- 75% of organizations lack a formal strategy to capture tacit knowledge
- ~1.2 million professionals retire annually in Spain alone
- 60–80% of an expert's intellectual value is tacit — undocumented and lost on departure
- Estimated organizational knowledge loss: ~€365B/year in Spain (25% of GDP)

## The 5 Protocols

| # | Protocol | What it does | Duration |
|---|----------|-------------|----------|
| 1 | **NUMA Capture** | LLM-guided 5-phase interview (incl. Negative Knowledge) | ~4h |
| 2 | **NUMA Structure** | Three-tier knowledge representation (Facts · Judgments · Intuitions) | Automated |
| 3 | **NUMA Validation** | Bidirectional fidelity check with expert sign-off | ~1h |
| 4 | **NUMA Access** | Hybrid retrieval via Reciprocal Rank Fusion (RRF) | Real-time |
| 5 | **NUMA Maintenance** | Semi-annual contradiction detection & update cycle | Ongoing |
| 6 | **Negative Knowledge** | Costly mistakes, anti-patterns & safety-critical warnings | ~30min |

## Key Results

- **64.8% reduction** in token consumption vs traditional multi-call baseline
- **Single tool invocation** — collapses 4 calls into 1
- **67% keyword overlap** with expert-validated gold answers
- **233–649ms** end-to-end query latency (after warm-up)

## Repository Structure

```
numa-pompiliu/
├── protocols/               # Detailed SOPs for each protocol
│   ├── 01-capture.md
│   ├── 02-structure.md
│   ├── 03-validation.md
│   ├── 04-access.md
│   ├── 05-negative-knowledge.md
│   └── 06-maintenance.md
├── implementation/
│   ├── numa-rag-server/     # MCP server: ChromaDB + Graphify + RRF
│   ├── numa-capture/        # LLM-guided interview pipeline (5 phases)
│   ├── numa-capture-web/    # Web UI: interviews, shadowing, industrial graph
│   └── numa-benchmark/      # Standardized evaluation suite
├── paper/                   # Academic paper (LaTeX + PDF)
├── CLAUDE.md                # Context for Claude Code
└── README.md
```

## Getting Started

```bash
# Clone the repo
git clone https://github.com/numa-pompiliu/numa-pompiliu
cd numa-pompiliu

# Install dependencies
pip install -r implementation/numa-rag-server/requirements.txt

# Run the RAG server
python implementation/numa-rag-server/server.py

# Run the benchmark
python implementation/numa-benchmark/run.py
```

## Citation

```bibtex
@article{boian2026numa,
  title={NUMA: A Methodology for Perpetuating Expert Knowledge through
         LLM-Guided Elicitation and Graph-Grounded Retrieval},
  author={Boian, Cristian},
  year={2026},
  note={Independent Research}
}
```

## License

MIT — see [LICENSE](LICENSE).
