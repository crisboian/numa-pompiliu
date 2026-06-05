# NUMA Capture Web 🏛️

Self-service web portal for conducting NUMA expert knowledge capture interviews.

## Architecture

```
Browser ──→ Web UI (HTML+JS) ──→ FastAPI Backend (:8765)
                                    ├── SQLite (sessions DB)
                                    ├── LLM (DeepSeek V4 Flash) — interviewer
                                    └── RAG Server — auto-index results
```

## Quick Start

```bash
# Install deps
cd implementation/numa-capture-web
uv pip install -r backend/requirements.txt

# Run (no LLM key = template prompts)
./start.sh
```

Open http://localhost:8765 in a browser.

## LLM Integration

Set `NUMA_LLM_KEY` to use DeepSeek as a real interviewer:

```bash
export NUMA_LLM_KEY=sk-your-key
export NUMA_LLM_MODEL=deepseek-chat  # V4 Flash
```

Without a key, the system uses pre-defined template prompts.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/phases` | Phase definitions |
| POST | `/api/sessions` | Create session |
| GET | `/api/sessions` | List sessions |
| GET | `/api/sessions/:id` | Get session state |
| POST | `/api/sessions/:id/start` | Start interview |
| POST | `/api/sessions/:id/answer` | Submit answer |
| GET | `/api/sessions/:id/chat` | Chat history |
| GET | `/api/sessions/:id/export` | Export as JSON |
| GET | `/api/sessions/:id/progress` | Phase progress |

## Integration with RAG

After completion, knowledge items auto-index into the NUMA RAG server
(configure via `NUMA_RAG_URL`, default: `http://localhost:9191`).

## Project Structure

```
implementation/numa-capture-web/
├── backend/
│   ├── server.py          # FastAPI routes & app
│   ├── database.py        # SQLAlchemy models
│   ├── llm.py             # LLM interviewer integration
│   └── rag_integration.py # RAG server auto-index
├── frontend/
│   └── index.html         # Single-page interview UI
├── start.sh               # Development start script
└── .env.template           # Environment config
```
