"""Tests for Reciprocal Rank Fusion (numa_rag.rrf)."""

from __future__ import annotations

import math

import pytest

from numa_rag.knowledge import RetrievedItem, Tier
from numa_rag.rrf import K_SMOOTHING, compute_rrf


def _item(statement: str, tier: Tier = Tier.FACTS, weight: float = 1.0) -> RetrievedItem:
    return RetrievedItem(
        statement=statement,
        tier=tier,
        weight=weight,
        source="test",
    )


def test_rrf_fuses_two_lists() -> None:
    graph = [_item("alpha"), _item("beta"), _item("gamma")]
    vector = [_item("beta"), _item("delta"), _item("alpha")]

    fused = compute_rrf(graph, vector)

    statements = [item.statement for item in fused]
    assert set(statements) == {"alpha", "beta", "gamma", "delta"}
    assert all(item.rrf_score > 0 for item in fused)


def test_rrf_scores_use_k_smoothing_60() -> None:
    """RRF(item) = sum(1 / (k + rank_i)) — verify k=60 math."""
    graph = [_item("only-in-graph")]
    vector = [_item("only-in-vector")]

    fused = compute_rrf(graph, vector)
    by_stmt = {item.statement: item for item in fused}

    expected = 1.0 / (K_SMOOTHING + 1)
    assert math.isclose(by_stmt["only-in-graph"].rrf_score, expected)
    assert math.isclose(by_stmt["only-in-vector"].rrf_score, expected)


def test_rrf_combines_scores_for_items_in_both_lists() -> None:
    """An item appearing in both lists at rank 1 should score 2 * 1/(k+1)."""
    graph = [_item("shared")]
    vector = [_item("shared")]

    fused = compute_rrf(graph, vector)

    assert len(fused) == 1
    expected = 2.0 / (K_SMOOTHING + 1)
    assert math.isclose(fused[0].rrf_score, expected)


def test_rrf_respects_rank_ordering() -> None:
    """Earlier ranks must produce higher RRF contributions."""
    graph = [_item("first"), _item("second"), _item("third")]
    vector: list[RetrievedItem] = []

    fused = compute_rrf(graph, vector)
    scores = {item.statement: item.rrf_score for item in fused}

    assert scores["first"] > scores["second"] > scores["third"]


def test_rrf_dedups_by_statement_text() -> None:
    """Two RetrievedItem objects with the same statement collapse to one entry."""
    graph = [_item("Same Statement"), _item("different")]
    vector = [_item("same statement"), _item("another")]  # case-insensitive dedup

    fused = compute_rrf(graph, vector)

    keys = {item.statement.lower().strip()[:80] for item in fused}
    assert len(fused) == len(keys)
    assert "same statement" in keys


def test_rrf_final_score_applies_tier_weight() -> None:
    """final_score = rrf_score * tier weight."""
    judgment = _item("judgment item", tier=Tier.JUDGMENTS, weight=0.7)
    fact = _item("fact item", tier=Tier.FACTS, weight=0.3)

    fused = compute_rrf([judgment], [fact])
    by_stmt = {item.statement: item for item in fused}

    assert math.isclose(
        by_stmt["judgment item"].final_score,
        by_stmt["judgment item"].rrf_score * 0.7,
    )
    assert math.isclose(
        by_stmt["fact item"].final_score,
        by_stmt["fact item"].rrf_score * 0.3,
    )
    # Higher tier weight should rank first when raw RRF is equal.
    assert fused[0].statement == "judgment item"


def test_rrf_custom_k_changes_scores() -> None:
    """Passing k explicitly should override the default smoothing."""
    graph = [_item("x")]
    vector = [_item("x")]

    fused_default = compute_rrf(graph, vector)
    fused_custom = compute_rrf([_item("x")], [_item("x")], k=10)

    assert not math.isclose(fused_default[0].rrf_score, fused_custom[0].rrf_score)
    assert math.isclose(fused_custom[0].rrf_score, 2.0 / (10 + 1))


def test_rrf_empty_inputs() -> None:
    assert compute_rrf([], []) == []
