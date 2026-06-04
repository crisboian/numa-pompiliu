"""ChromaDB vector store for semantic search over knowledge statements."""

from __future__ import annotations

import logging
from typing import Sequence

from numa_rag.knowledge import KnowledgeDocument, KnowledgeStatement, RetrievedItem, Tier

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb.config import Settings

    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False
    logger.warning("chromadb not available; using in-memory fallback")

try:
    from sentence_transformers import SentenceTransformer

    HAS_SENTENCE = True
except ImportError:
    HAS_SENTENCE = False
    logger.warning("sentence-transformers not available; using simple fallback")


class _MemoryStore:
    """Fallback in-memory store when ChromaDB is not available."""

    def __init__(self) -> None:
        self.documents: list[dict] = []

    def add(self, documents: list[str], metadatas: list[dict]) -> None:
        for doc, meta in zip(documents, metadatas):
            self.documents.append({"document": doc, "metadata": meta})

    def query(
        self, query_texts: list[str], n_results: int = 10
    ) -> list[list[RetrievedItem]]:
        """Simple keyword-based search as fallback."""
        query = query_texts[0].lower() if query_texts else ""
        tokens = query.split()
        scored: list[tuple[float, RetrievedItem]] = []

        for entry in self.documents:
            doc_lower = entry["document"].lower()
            score = sum(1 for t in tokens if t in doc_lower)
            meta = entry["metadata"]
            if score > 0:
                tier = Tier(meta.get("tier", "facts"))
                scored.append(
                    (
                        score,
                        RetrievedItem(
                            statement=entry["document"],
                            tier=tier,
                            weight=meta.get("weight", 0.3),
                            source=meta.get("source", "unknown"),
                            expert_name=meta.get("expert_name", ""),
                            conditions=meta.get("conditions", []),
                        ),
                    )
                )

        scored.sort(key=lambda x: x[0], reverse=True)
        return [[item for _, item in scored[:n_results]]]

    def count(self) -> int:
        return len(self.documents)


class ChromaStore:
    """Vector store for semantic search over knowledge statements."""

    def __init__(
        self, collection_name: str = "numa_knowledge", persist_dir: str = ""
    ) -> None:
        self.collection_name = collection_name
        self._embedder = None
        self._collection = None
        self._fallback = _MemoryStore()

        if HAS_CHROMA:
            try:
                settings = Settings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                )
                client = chromadb.Client(settings)
                self._collection = client.get_or_create_collection(
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info("ChromaDB collection '%s' ready", collection_name)
            except Exception as exc:
                logger.warning("ChromaDB init failed: %s; using fallback", exc)
        else:
            logger.info("Using in-memory fallback store")

    def _get_embedder(self):
        """Lazy-load sentence transformer."""
        if self._embedder is None and HAS_SENTENCE:
            try:
                self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
            except Exception as exc:
                logger.warning("Failed to load embedder: %s", exc)
        return self._embedder

    def add_knowledge(self, doc: KnowledgeDocument) -> int:
        """Index all statements from a knowledge document."""
        statements = doc.all_statements()
        if not statements:
            return 0

        documents = []
        metadatas = []
        ids = []

        for stmt in statements:
            documents.append(stmt.statement)
            metadatas.append(
                {
                    "tier": stmt.tier.value,
                    "weight": str(stmt.weight),
                    "source": stmt.source,
                    "expert_name": stmt.expert_name,
                    "session_id": stmt.session_id,
                    "conditions": ",".join(stmt.conditions),
                    "timestamp": stmt.timestamp,
                }
            )
            ids.append(stmt.id)

        if self._collection is not None:
            try:
                self._collection.add(
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids,
                )
            except Exception as exc:
                logger.warning("ChromaDB add failed: %s; using fallback", exc)
                for d, m in zip(documents, metadatas):
                    self._fallback.add([d], [m])
        else:
            for d, m in zip(documents, metadatas):
                self._fallback.add([d], [m])

        return len(statements)

    def search(self, query: str, limit: int = 10) -> list[RetrievedItem]:
        """Search for semantically similar knowledge statements."""
        if self._collection is not None:
            try:
                embedder = self._get_embedder()
                if embedder is not None:
                    query_emb = embedder.encode(query).tolist()
                    results = self._collection.query(
                        query_embeddings=[query_emb],
                        n_results=limit,
                        include=["metadatas", "documents", "distances"],
                    )
                    return self._parse_chroma_results(results)
            except Exception as exc:
                logger.warning("ChromaDB query failed: %s; using fallback", exc)

        # Fallback
        results = self._fallback.query([query], n_results=limit)
        return results[0] if results else []

    def _parse_chroma_results(self, results: dict) -> list[RetrievedItem]:
        """Parse ChromaDB query results into RetrievedItems."""
        items: list[RetrievedItem] = []
        if not results.get("ids") or not results["ids"][0]:
            return items

        for i, doc_id in enumerate(results["ids"][0]):
            meta = (results.get("metadatas") or [{}])[0][i] if results.get("metadatas") else {}
            doc = (results.get("documents") or [[]])[0][i] if results.get("documents") else ""
            tier_str = meta.get("tier", "facts")
            try:
                tier = Tier(tier_str)
            except ValueError:
                tier = Tier.FACTS

            conditions_raw = meta.get("conditions", "")
            conditions = conditions_raw.split(",") if conditions_raw else []

            items.append(
                RetrievedItem(
                    statement=doc,
                    tier=tier,
                    weight=float(meta.get("weight", TIER_WEIGHTS.get(tier, 0.3))),
                    source=meta.get("source", "vector_store"),
                    expert_name=meta.get("expert_name", ""),
                    conditions=conditions,
                )
            )

        return items

    def stats(self) -> dict[str, int]:
        """Return collection statistics."""
        if self._collection is not None:
            try:
                count = self._collection.count()
                return {"chunks": count}
            except Exception:
                pass
        return {"chunks": self._fallback.count()}


# Need TIER_WEIGHTS for fallback parsing
from numa_rag.knowledge import TIER_WEIGHTS  # noqa: E402, F811
