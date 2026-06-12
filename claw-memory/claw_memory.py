"""
NUMA Memory for Claw — Knowledge-Grounded Agent Memory
Implements NUMA methodology (Capture → Structure → Validation → Access → Maintenance)
for Claw's persistent memory system.

Tiers:
- FACTS (0.3): Documented facts — IPs, hostnames, credentials, config values
- JUDGMENTS (0.7): Expert decisions with rationale — why we chose X over Y
- INTUITIONS (0.5): Heuristics, preferences, unwritten patterns
"""

import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

# ============================================================
# Data Models (compatible with NUMA paper models)
# ============================================================

TIER_WEIGHTS = {
    "facts": 0.3,
    "judgments": 0.7,
    "intuitions": 0.5,
}

class KnowledgeStatement:
    """A single knowledge statement with tier classification."""
    def __init__(self, statement: str, tier: str, source: str,
                 expert_name: str = "Claw", conditions: list = None,
                 confidence: float = 1.0):
        self.id = f"ks_{uuid.uuid4().hex[:12]}"
        self.statement = statement
        self.tier = tier
        self.weight = TIER_WEIGHTS.get(tier, 0.3)
        self.source = source
        self.expert_name = expert_name
        self.conditions = conditions or []
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.confidence = confidence

    def to_dict(self):
        return {
            "id": self.id,
            "statement": self.statement,
            "tier": self.tier,
            "weight": self.weight,
            "source": self.source,
            "expert_name": self.expert_name,
            "conditions": self.conditions,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
        }


class RetrievedItem:
    """Item returned from retrieval with fusion scores."""
    def __init__(self, statement: str, tier: str, weight: float, source: str,
                 expert_name: str = "", conditions: list = None):
        self.statement = statement
        self.tier = tier
        self.weight = weight
        self.source = source
        self.expert_name = expert_name
        self.conditions = conditions or []
        self.graph_rank = None
        self.vector_rank = None
        self.rrf_score = 0.0
        self.final_score = 0.0

    def to_dict(self):
        return {
            "statement": self.statement,
            "tier": self.tier,
            "weight": self.weight,
            "source": self.source,
            "expert_name": self.expert_name,
            "conditions": self.conditions,
            "graph_rank": self.graph_rank,
            "vector_rank": self.vector_rank,
            "rrf_score": self.rrf_score,
            "final_score": self.final_score,
        }


# ============================================================
# NUMA Protocol 2: Structure — Knowledge Indexer
# ============================================================

class ClawKnowledgeIndexer:
    """Reads Claw's workspace files and structures them into NUMA tiers."""

    # File classification rules
    FILE_TIER_MAP = {
        "MEMORY.md": "judgments",      # Curated long-term insights
        "SOUL.md": "intuitions",       # Personality, vibe
        "IDENTITY.md": "facts",        # Name, persona
        "USER.md": "facts",            # User info, location
        "TOOLS.md": "facts",           # IPs, hostnames, commands
        "AGENTS.md": "judgments",      # Rules, conventions
        "HEARTBEAT.md": "facts",       # Task lists
    }

    def __init__(self, workspace_path: str = "/root/.openclaw/workspace"):
        self.workspace = Path(workspace_path)
        self.memory_dir = self.workspace / "memory"
        self.statements: list[KnowledgeStatement] = []

    def index_all(self) -> list[KnowledgeStatement]:
        """Index all workspace files."""
        print(f"📚 Indexing workspace: {self.workspace}")
        self.statements = []

        # Index main config files
        for filename, tier in self.FILE_TIER_MAP.items():
            filepath = self.workspace / filename
            if filepath.exists():
                self._index_file(filepath, tier)
                self._extract_atomic_facts(filepath)

        # Index daily memory files
        if self.memory_dir.exists():
            for memfile in sorted(self.memory_dir.glob("*.md")):
                self._index_file(memfile, "judgments")
                self._extract_atomic_facts(memfile)

        print(f"✅ Indexed {len(self.statements)} knowledge statements")
        return self.statements

    def _extract_atomic_facts(self, filepath: Path):
        """Extract atomic facts (IPs, URLs, tokens, etc.) from a file."""
        try:
            from fact_extractor import extract_facts_only
            text = filepath.read_text()
            facts = extract_facts_only(text, filepath.name)
            for f in facts:
                # Build a clean fact statement
                cat_labels = {
                    "IP/endpoint": "IP address",
                    "URL": "URL",
                    "model": "AI model",
                    "credential": "Credential",
                    "token_candidate": "API token",
                    "port": "Port",
                    "hostname": "Hostname",
                    "filepath": "File path",
                    "chat_id": "Chat ID",
                    "email": "Email",
                    "model_spec": "Model spec",
                }
                label = cat_labels.get(f["category"], f["category"])
                statement = f"{label}: {f['value']} (source: {f['source']})"
                ks = KnowledgeStatement(
                    statement=statement,
                    tier="facts",
                    source=f"{f['source']} → atomic_{f['category']}",
                )
                self.statements.append(ks)
        except Exception:
            pass

    def _index_file(self, filepath: Path, default_tier: str):
        """Extract knowledge statements from a single file."""
        try:
            content = filepath.read_text()
        except Exception:
            return

        filename = filepath.name
        # Split on markdown headers and blank lines to get logical chunks
        sections = self._split_into_sections(content, filename)

        for section_text, header in sections:
            tier = self._classify_section(header, section_text, default_tier)
            statement = self._clean_statement(section_text)
            if len(statement) < 10:
                continue
            ks = KnowledgeStatement(
                statement=statement,
                tier=tier,
                source=f"{filename}{' → ' + header if header else ''}",
                conditions=self._extract_conditions(section_text, header),
            )
            self.statements.append(ks)

    def _split_into_sections(self, content: str, filename: str) -> list:
        """Split markdown content into logical sections."""
        sections = []
        # Try header-based splitting
        header_pattern = re.findall(r'^(#{1,3})\s+(.+)$', content, re.MULTILINE)
        header_positions = [(m.start(), m.group(1), m.group(2))
                           for m in re.finditer(r'^(#{1,3})\s+(.+)$', content, re.MULTILINE)]

        if header_positions:
            for i, (pos, level, header) in enumerate(header_positions):
                start = pos + len(level) + len(header) + 2  # after ## Header
                end = header_positions[i+1][0] if i+1 < len(header_positions) else len(content)
                section_text = content[start:end].strip()
                if section_text:
                    sections.append((section_text, header))
        else:
            # No headers, split on double newlines
            paragraphs = re.split(r'\n\n+', content.strip())
            for para in paragraphs:
                if para.strip():
                    sections.append((para.strip(), ""))

        return sections

    def _classify_section(self, header: str, text: str, default_tier: str) -> str:
        """Classify a section into a NUMA tier."""
        header_lower = header.lower()
        text_first_100 = text[:100].lower()

        # Facts: IPs, hostnames, URLs, credentials, numeric data
        if any(kw in header_lower for kw in ['url', 'ip', 'host', 'credential', 'setup',
                                              'config', 'address', 'endpoint', 'api']):
            return "facts"
        if re.search(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', text_first_100):
            return "facts"
        if re.search(r'https?://', text_first_100):
            return "facts"

        # Judgments: decisions, preferences marked clearly
        if any(kw in header_lower for kw in ['decision', 'preference', 'rule', 'policy',
                                              'boundary', 'red line', 'important']):
            return "judgments"

        # Intuitions: personality, vibe, style
        if any(kw in header_lower for kw in ['vibe', 'persona', 'style', 'tone', 'voice']):
            return "intuitions"

        return default_tier

    def _clean_statement(self, text: str) -> str:
        """Clean and normalize a section into a single statement."""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        # Truncate very long sections
        if len(text) > 800:
            text = text[:800] + "..."
        return text

    def _extract_conditions(self, text: str, header: str) -> list:
        """Extract conditions/context markers from text."""
        conditions = []
        # Look for conditional language
        conditionals = re.findall(r'(?:if|when|unless|except|but|however|⚠️)([^.!?\n]{10,100})',
                                  text, re.IGNORECASE)
        for c in conditionals[:3]:
            conditions.append(c.strip())
        return conditions


# ============================================================
# NUMA Protocol 4: Access — ChromaDB + Graph + RRF
# ============================================================

K_SMOOTHING = 60  # From Cormack et al. SIGIR 2009

class ClawMemoryStore:
    """Hybrid memory store: ChromaDB (vector) + Knowledge Graph + RRF fusion."""

    def __init__(self, persist_dir: str = "/root/numa-memory/data"):
        self.persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)

        # ChromaDB for vector search
        self.chroma = chromadb.PersistentClient(
            path=os.path.join(persist_dir, "chroma"),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        self.collection_name = "claw_knowledge"
        self._init_collection()
        self.statements: list[KnowledgeStatement] = []

    def _init_collection(self):
        """Initialize or get the ChromaDB collection."""
        try:
            self.collection = self.chroma.get_collection(self.collection_name)
        except Exception:
            self.collection = self.chroma.create_collection(
                name=self.collection_name,
                metadata={"description": "Claw's NUMA-structured knowledge"},
            )

    def index_statements(self, statements: list[KnowledgeStatement]):
        """Index knowledge statements into ChromaDB."""
        self.statements = statements

        # Clear existing
        try:
            existing = self.collection.get()
            if existing["ids"]:
                self.collection.delete(ids=existing["ids"])
        except Exception:
            pass

        # Batch add
        if not statements:
            return

        ids = [s.id for s in statements]
        documents = [s.statement for s in statements]
        metadatas = [{
            "tier": s.tier,
            "weight": s.weight,
            "source": s.source,
            "timestamp": s.timestamp,
        } for s in statements]

        self.collection.add(ids=ids, documents=documents, metadatas=metadatas)
        print(f"💾 Indexed {len(statements)} statements in ChromaDB")

        # Save statement cache for fast queries
        import json
        cache_path = os.path.join(self.persist_dir, "statements_cache.json")
        cache_data = [{
            "id": s.id,
            "statement": s.statement,
            "tier": s.tier,
            "weight": s.weight,
            "source": s.source,
            "timestamp": s.timestamp,
        } for s in statements]
        with open(cache_path, "w") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        print(f"📋 Cached {len(cache_data)} statements to {cache_path}")

    def search_vector(self, query: str, n_results: int = 10) -> list[RetrievedItem]:
        """Vector search via ChromaDB."""
        if not self.statements:
            return []

        results = self.collection.query(
            query_texts=[query],
            n_results=min(n_results, len(self.statements)),
        )

        items = []
        stmt_by_id = {s.id: s for s in self.statements}

        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                ks = stmt_by_id.get(doc_id)
                if ks:
                    dist = results.get("distances", [[0]] * len(results["ids"][0]))
                    score = 1.0 / (1.0 + (dist[0][i] if dist and dist[0] else 0))
                    item = RetrievedItem(
                        statement=ks.statement,
                        tier=ks.tier,
                        weight=ks.weight,
                        source=ks.source,
                        expert_name=ks.expert_name,
                        conditions=ks.conditions,
                    )
                    item.rrf_score = score
                    item.final_score = score * ks.weight
                    items.append(item)

        return items

    def search_graph(self, query: str, n_results: int = 10) -> list[RetrievedItem]:
        """Keyword-based graph-style search (keyword overlap + tier weight)."""
        if not self.statements:
            return []

        query_terms = set(query.lower().split())
        if not query_terms:
            return []

        scored = []
        for ks in self.statements:
            stmt_lower = ks.statement.lower()
            # Count keyword matches
            matches = sum(1 for term in query_terms if term in stmt_lower)
            if matches > 0:
                # Bonus for title/header matches in source
                source_bonus = 1.0
                source_lower = ks.source.lower()
                if any(term in source_lower for term in query_terms):
                    source_bonus = 2.0

                score = (matches / len(query_terms)) * source_bonus
                item = RetrievedItem(
                    statement=ks.statement,
                    tier=ks.tier,
                    weight=ks.weight,
                    source=ks.source,
                    expert_name=ks.expert_name,
                    conditions=ks.conditions,
                )
                item.rrf_score = score
                item.final_score = score * ks.weight
                scored.append(item)

        # Sort by score descending
        scored.sort(key=lambda x: x.final_score, reverse=True)
        return scored[:n_results]

    def compute_rrf(self, graph_results: list[RetrievedItem],
                    vector_results: list[RetrievedItem],
                    k: int = K_SMOOTHING) -> list[RetrievedItem]:
        """Fuse graph and vector results using Reciprocal Rank Fusion.

        RRF(item) = Σ_{i ∈ {graph, vector}} 1 / (k + rank_i(item))
        """
        scores: dict[str, float] = {}
        items_by_key: dict[str, RetrievedItem] = {}

        def item_key(item: RetrievedItem) -> str:
            return item.statement.strip()[:80].lower()

        for rank, item in enumerate(graph_results, start=1):
            key = item_key(item)
            item.graph_rank = rank
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank)
            items_by_key[key] = item

        for rank, item in enumerate(vector_results, start=1):
            key = item_key(item)
            item.vector_rank = rank
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank)
            if key not in items_by_key:
                items_by_key[key] = item

        for key, item in items_by_key.items():
            item.rrf_score = scores[key]
            item.final_score = scores[key] * item.weight

        sorted_items = sorted(items_by_key.values(),
                             key=lambda x: x.final_score, reverse=True)
        return sorted_items

    def query(self, query: str, mode: str = "kgaa_rrf",
              top_n: int = 5) -> dict:
        """Execute a knowledge query.

        Modes:
        - vector_only: ChromaDB semantic search
        - graph_only: Keyword-based graph traversal
        - kgaa: Both, concatenated
        - kgaa_rrf: Both, fused via RRF (recommended)
        """
        start = time.time()

        vector_results = self.search_vector(query, n_results=10)
        graph_results = self.search_graph(query, n_results=10)

        if mode == "vector_only":
            items = vector_results[:top_n]
        elif mode == "graph_only":
            items = graph_results[:top_n]
        elif mode == "kgaa_rrf":
            items = self.compute_rrf(vector_results, graph_results)[:top_n]
        else:  # kgaa
            # Deduplicate and interleave
            seen = set()
            items = []
            for v, g in zip(vector_results, graph_results):
                for item in [v, g]:
                    key = item.statement[:80].lower()
                    if key not in seen:
                        seen.add(key)
                        items.append(item)
            items = items[:top_n]

        latency = (time.time() - start) * 1000

        sources = []
        for item in items:
            sources.append({
                "statement": item.statement[:200],
                "tier": item.tier,
                "source": item.source,
                "score": round(item.final_score, 4),
                "rrf_score": round(item.rrf_score, 4) if item.rrf_score else 0,
                "graph_rank": item.graph_rank,
                "vector_rank": item.vector_rank,
            })

        return {
            "query": query,
            "mode": mode,
            "results_count": len(items),
            "latency_ms": round(latency, 1),
            "sources": sources,
            "top_answer": items[0].statement[:500] if items else "No results found.",
        }


# ============================================================
# NUMA Protocol 3: Validation — Self-check
# ============================================================

def validate_store(store: ClawMemoryStore, test_queries: list[str] = None):
    """Run validation queries and report fidelity."""
    if test_queries is None:
        test_queries = [
            "Who is Cristian and where does he live?",
            "What is the Proxmox host IP?",
            "How does Claw communicate in group chats?",
            "What model does Claw use?",
        ]

    print("\n🔍 NUMA Validation Report")
    print("=" * 60)
    for query in test_queries:
        result = store.query(query, mode="kgaa_rrf", top_n=3)
        print(f"\nQ: {query}")
        print(f"   Mode: {result['mode']} | Latency: {result['latency_ms']}ms | Results: {result['results_count']}")
        if result["sources"]:
            for i, s in enumerate(result["sources"][:2]):
                print(f"   [{i+1}] {s['tier']:12s} (score={s['score']:.4f}) {s['source']}")
                print(f"       {s['statement'][:120]}...")

    return True


# ============================================================
# NUMA Protocol 5: Maintenance — Re-indexing
# ============================================================

def maintenance_reindex(store: ClawMemoryStore, workspace_path: str = "/root/.openclaw/workspace"):
    """Re-index all knowledge (Maintenance protocol)."""
    print("🔄 NUMA Maintenance: Re-indexing all knowledge...")
    indexer = ClawKnowledgeIndexer(workspace_path)
    statements = indexer.index_all()
    store.index_statements(statements)
    print("✅ Maintenance complete.")

    # Report tier distribution
    tiers = {"facts": 0, "judgments": 0, "intuitions": 0}
    for s in statements:
        tiers[s.tier] = tiers.get(s.tier, 0) + 1
    print(f"📊 Tiers: {tiers}")


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NUMA Memory for Claw")
    parser.add_argument("--index", action="store_true", help="Index all knowledge")
    parser.add_argument("--query", type=str, help="Search query")
    parser.add_argument("--mode", type=str, default="kgaa_rrf",
                       choices=["vector_only", "graph_only", "kgaa", "kgaa_rrf"])
    parser.add_argument("--validate", action="store_true", help="Run validation")
    parser.add_argument("--top", type=int, default=5)

    args = parser.parse_args()

    store = ClawMemoryStore()

    if args.index:
        maintenance_reindex(store)
    elif args.validate:
        if len(store.statements) == 0:
            maintenance_reindex(store)
        validate_store(store)
    elif args.query:
        if len(store.statements) == 0:
            maintenance_reindex(store)
        result = store.query(args.query, mode=args.mode, top_n=args.top)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # Default: index + validate
        maintenance_reindex(store)
        validate_store(store)
