"""Reciprocal Rank Fusion (RRF) — fuses ranked results from multiple sources."""

from __future__ import annotations

import heapq
from collections import defaultdict
from typing import Sequence

from numa_rag.knowledge import RetrievedItem


K_SMOOTHING = 60
"""Smoothing constant k=60 per Cormack et al. SIGIR 2009."""


def compute_rrf(
    graph_results: Sequence[RetrievedItem],
    vector_results: Sequence[RetrievedItem],
    k: int = K_SMOOTHING,
) -> list[RetrievedItem]:
    """Fuse graph and vector results using Reciprocal Rank Fusion.

    RRF(item) = Σ_{i ∈ {graph, vector}} 1 / (k + rank_i(item))

    Args:
        graph_results: Items ranked by graph traversal.
        vector_results: Items ranked by vector similarity.
        k: Smoothing constant (default 60).

    Returns:
        Items sorted by descending RRF score.
    """
    scores: dict[str, float] = defaultdict(float)
    items_by_id: dict[str, RetrievedItem] = {}

    # Assign ranks and accumulate RRF scores
    for rank, item in enumerate(graph_results, start=1):
        item_id = _item_key(item)
        item.graph_rank = rank
        scores[item_id] += 1.0 / (k + rank)
        items_by_id[item_id] = item

    for rank, item in enumerate(vector_results, start=1):
        item_id = _item_key(item)
        item.vector_rank = rank
        scores[item_id] += 1.0 / (k + rank)
        if item_id not in items_by_id:
            items_by_id[item_id] = item

    # Apply RRF score and tier weight
    for item_id, item in items_by_id.items():
        item.rrf_score = scores[item_id]
        item.final_score = scores[item_id] * item.weight

    # Sort by final score descending
    sorted_items = sorted(
        items_by_id.values(), key=lambda x: x.final_score, reverse=True
    )

    return sorted_items


def _item_key(item: RetrievedItem) -> str:
    """Return a dedup key for a retrieved item."""
    return item.statement.strip()[:80].lower()
