# NUMA Protocol 4: Access — Hybrid Retrieval via Reciprocal Rank Fusion

**Purpose**: Provide accurate, traceable answers to knowledge queries by fusing structural graph traversal with semantic vector search.

**Latency target**: <1 second per query after warm-up
**Query format**: Natural language question

---

## Retrieval Architecture

```
User Query
    │
    ▼
┌──────────────────────────────┐
│  Query Expansion (optional)  │  ← HyDE: generate hypothetical answer
└──────────────────────────────┘
    │
    ├──────────────────┬──────────────────┐
    ▼                  ▼                  ▼
┌──────────┐    ┌──────────┐    ┌──────────────┐
│ Graphify │    │ ChromaDB │    │ BM25 (plans) │
│ Traversal│    │Semantic  │    │ Lexical      │
│          │    │ Search   │    │ Search       │
│Ranked    │    │Ranked    │    │ Ranked       │
│results A │    │results B │    │ results C    │
└──────────┘    └──────────┘    └──────────────┘
    │              │              │
    └──────────────┼──────────────┘
                   ▼
    ┌──────────────────────────────┐
    │  Reciprocal Rank Fusion      │
    │  RRF(item) = Σ 1/(k + rank)  │
    │  k = 60                      │
    └──────────────────────────────┘
                   │
                   ▼
    ┌──────────────────────────────┐
    │  Weight Apply + Source Cite  │
    │  Facts ×0.3 / Judgments ×0.7│
    │  / Intuitions ×0.5          │
    └──────────────────────────────┘
                   │
                   ▼
    ┌──────────────────────────────┐
    │  LLM Response Assembly       │
    │  (answer + sources + confidence)│
    └──────────────────────────────┘
```

---

## Step 1: Query Processing

### Preprocessing
1. Strip stop words and normalize casing
2. Detect query type: lookup (factual) / reasoning (judgment) / diagnostic (intuition)
3. Optionally generate a hypothetical answer using HyDE technique:
   > "Generate a concise hypothetical answer to: {query}"
   Use this as an additional search query for ChromaDB

---

## Step 2: Graph Traversal (Graphify)

### Semantic Node Matching
1. Identify relevant graph nodes from the query using semantic matching
2. Traverse depth-1 neighbors of matched nodes
3. Score paths by:
   - Node relevance to query
   - Edge weight (0.3/0.5/0.7 based on tier)
   - Path depth (shorter paths = higher weight)

### Graph Query
```json
{
  "query": "Can the K-700 operate at 195°?",
  "nodes_matched": ["K-700", "operating_range", "gasket"],
  "traversal_depth": 1,
  "results": [
    {"node": "gasket_melt_threshold", "type": "judgment", "weight": 0.7, "score": 0.89},
    {"node": "manual_temp_range", "type": "fact", "weight": 0.3, "score": 0.85},
    {"node": "incident_234", "type": "fact", "weight": 0.3, "score": 0.72}
  ]
}
```

---

## Step 3: Vector Search (ChromaDB)

### Query Embedding
1. Embed the user query using all-MiniLM-L6-v2
2. Search ChromaDB with n_results = 20
3. Return results with metadata (tier, weight, source, conditions)

### ChromaDB Query
```python
results = chroma_collection.query(
    query_embeddings=[embedding],
    n_results=20,
    include=["metadatas", "distances", "documents"]
)
```

---

## Step 4: Reciprocal Rank Fusion

Combine rankings from graph and vector searches:

```
RRF(item) = Σ_{i ∈ {graph, rag}} 1 / (k + rank_i(item))

where:
- k = 60 (smoothing constant, per Cormack et al. SIGIR 2009)
- rank_i(item) = position of item in results set i (1-indexed)
```

### Fusion Example

| Item | Graph rank | Vector rank | RRF Score |
|------|-----------|-------------|-----------|
| A: gasket_melt_threshold | 1 | 3 | 1/61 + 1/63 = 0.0323 |
| B: manual_temp_range | 2 | 5 | 1/62 + 1/65 = 0.0315 |
| C: incident_234 | 5 | 1 | 1/65 + 1/61 = 0.0323 |

Items are sorted by descending RRF score.

---

## Step 5: Weight Application & Source Citation

Final scoring applies tier weights:

```
final_score(item) = RRF_score(item) × tier_weight(item)
```

### Response Assembly

The LLM constructs the final answer:

1. For each top-3 RRF result, cite:
   - Who said it (expert name + session date)
   - What they said (verbatim or paraphrased)
   - The tier weight (Facts / Judgment / Intuition)
   - Confidence level (Low / Medium / High)

2. If sources disagree, flag the contradiction explicitly

3. Response format:

```
**Q**: Can the K-700 operate at 195°?

**Pepe García** (session 2026-03-15, Judgment weight=0.7):
"Never exceed 185° even though the manual says 190°. The right-hand gasket is softer than specification."

**Manual K-700** p.34 (Fact weight=0.3):
"Operating range: 170–190°C."

**Incident #234** (2019, Fact weight=0.3):
Right gasket melted at 193°C.

→ **Recommendation**: Do not exceed 185°C.
→ **Confidence**: High (converging sources: expert judgment + incident evidence).
```

---

## Step 6: Conditional Application

Before returning, check if any retrieved knowledge has attached conditions. If so, include them in the response:

> **Conditions apply**: This rule is only valid when ambient temperature < 5°C. For warmer conditions, 190°C is acceptable.

---

## Caching Strategy

| Cache Level | TTL | Scope |
|-------------|-----|-------|
| Query embedding | Session | Avoid re-embedding identical queries |
| Graph traversal | 1 hour | Graph topology changes rarely |
| ChromaDB results | 5 min | Static index between maintenance cycles |
| Final response | 1 hour | Identical Q&A pairs |

---

## Performance Targets

| Metric | Target | Measured |
|--------|--------|----------|
| Cold start latency | <2s | — |
| Warm query latency | <1s | 233-649ms |
| Throughput | 10 qps | — |
| Recall@5 | >85% | — |
