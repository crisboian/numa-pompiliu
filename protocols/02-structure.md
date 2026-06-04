# NUMA Protocol 2: Structure — Three-Tier Knowledge Representation

**Purpose**: Transform raw interview output into a structured, queryable knowledge representation using a dual-store architecture (knowledge graph + vector database).

**Automation**: Fully automated. Triggered after Capture completes.

---

## Architecture

```
Raw Interview JSON
        │
        ▼
┌─────────────────────────────┐
│  1. Tier Classification     │  ← Statement → Facts / Judgments / Intuitions
└─────────────────────────────┘
        │
        ├──────────────────────────────┐
        ▼                              ▼
┌──────────────────┐       ┌──────────────────┐
│ Knowledge Graph   │       │ Vector Database  │
│ (Graphify)        │       │ (ChromaDB)       │
│                   │       │                  │
│ Nodes: entities   │       │ Chunks: tiered   │
│ Edges: relations  │       │ statements       │
│ 83K nodes/177K    │       │ all-MiniLM-L6-v2 │
│ edges (example)   │       │ 384 dimensions   │
└──────────────────┘       └──────────────────┘
        │                          │
        └──────────┬───────────────┘
                   ▼
        ┌──────────────────────┐
        │   RRF Fusion Layer   │  ← k=60
        └──────────────────────┘
```

---

## Step 1: Tier Classification

Classify each knowledge statement into one of three tiers based on source and content.

| Tier | Type | Weight | Source | Characteristics |
|------|------|--------|--------|-----------------|
| 1 | Facts | 0.3 | Manuals, SOPs, regulations | Verifiable, documented, objective |
| 2 | Judgments | 0.7 | Expert decisions with rationale | Subjective, experience-based, context-dependent |
| 3 | Intuitions | 0.5 | Expert narrative, "sixth sense" | Heuristic, pattern-based, hard to verbalize |

### Classification Rules

```
IF source == "manual" OR "SOP" OR "regulation":
    → Facts (0.3)

IF source is expert testimony AND contains rationale ("because", "since", "due to"):
    → Judgments (0.7)

IF source is expert testimony AND is heuristic ("always", "never", "look for", "listen for"):
    → Intuitions (0.5)

IF source is expert AND contains a conditional ("if", "when", "unless"):
    → Judgments (0.7) — condition is attached as metadata
```

---

## Step 2: Knowledge Graph Construction (Graphify)

### Nodes
Each distinct entity becomes a node:
- **Equipment**: K-700, pressure valve, conveyor belt #3
- **Processes**: calibration, startup, shutdown
- **Concepts**: safety margin, thermal expansion
- **People**: Pepe García, successors

### Edges
Relationships between nodes with types:
- `contains`: machine → component
- `affects`: temperature → gasket integrity
- `overrides`: expert judgment → documented procedure
- `depends_on`: process → equipment
- `conflicts_with`: judgment → documented fact (flagged for maintenance)

### Node Attributes
```json
{
  "id": "k700_calibration",
  "name": "K-700 Calibration",
  "type": "process",
  "tier": "judgment",
  "weight": 0.7,
  "conditions": ["ambient_temp < 5°C"],
  "source": "interview_phase_b",
  "session_id": "..."
}
```

---

## Step 3: Vector Indexing (ChromaDB)

### Chunking Strategy
- **Facts**: Full document paragraphs (preserve context)
- **Judgments**: Each judgment statement + its rationale as one chunk
- **Intuitions**: Each heuristic + context as one chunk

### Metadata Per Chunk
```json
{
  "tier": "judgment",
  "weight": 0.7,
  "source": "interview_phase_b",
  "session_id": "...",
  "expert": "Pepe García",
  "conditions": ["ambient_temp < 5°C"],
  "timestamp": "2026-03-15T10:30:00Z"
}
```

### Embedding Model
- **Model**: all-MiniLM-L6-v2
- **Dimensions**: 384
- **Max sequence length**: 256 tokens (chunk accordingly)

---

## Step 4: Cross-Referencing

After both stores are populated, generate cross-references:

1. **Link graph nodes to ChromaDB chunks** — each node stores chroma_id
2. **Link ChromaDB chunks to graph nodes** — each chunk stores graph_node_ids
3. **Generate tier-crossing edges** — facts that contradict judgments get a `conflicts_with` edge

---

## Storage Cleanup

After indexing, purge from the raw Capture JSON:
- Filler phrases ("um", "let me think", repetition)
- Personal identifiable information (PII) — hash names unless needed for context
- Off-topic digressions (detected via LLM classifier, threshold: <0.3 relevance)
