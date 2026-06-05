"""NUMA Capture Web — integration with NUMA RAG Server for auto-indexing."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("numa-capture-rag")

RAG_SERVER_URL = os.environ.get("NUMA_RAG_URL", "http://localhost:9191")
RAG_ENABLED = os.environ.get("NUMA_RAG_ENABLED", "true").lower() == "true"


async def index_knowledge_items(
    session_data: dict[str, Any],
    knowledge_items: list[dict[str, Any]],
    conversation: list[dict[str, Any]],
) -> dict[str, Any]:
    """Send captured knowledge items to the RAG server for indexing.

    Returns indexing result summary.
    """
    if not RAG_ENABLED:
        logger.info("RAG indexing disabled via NUMA_RAG_ENABLED=false")
        return {"indexed": False, "reason": "RAG indexing disabled"}

    try:
        payload = {
            "session_id": session_data["id"],
            "expert_name": session_data.get("expert_name", ""),
            "expert_role": session_data.get("expert_role", ""),
            "domain": session_data.get("domain", ""),
            "organization": session_data.get("organization", ""),
            "knowledge_items": knowledge_items,
            "conversation_summary": _build_summary(conversation),
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{RAG_SERVER_URL}/ingest",
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            logger.info(f"Indexed {len(knowledge_items)} items to RAG server")
            return {"indexed": True, "result": result}

    except httpx.RequestError as e:
        logger.warning(f"RAG server unreachable ({e}). Items saved locally only.")
        return {"indexed": False, "reason": f"RAG server unreachable: {str(e)}"}
    except Exception as e:
        logger.error(f"RAG indexing failed: {e}")
        return {"indexed": False, "reason": str(e)}


def _build_summary(conversation: list[dict[str, Any]]) -> str:
    """Build a compact summary of the conversation for RAG context."""
    items = []
    for m in conversation[-20:]:  # Last 20 messages
        role = m.get("role", "?")
        content = m.get("content", "")
        # Truncate long messages
        if len(content) > 200:
            content = content[:200] + "..."
        items.append(f"[{role}] {content}")
    return "\n".join(items)


async def query_existing_docs(
    domain: str, query: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Query the RAG server for existing documentation on a topic."""
    if not RAG_ENABLED:
        return []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{RAG_SERVER_URL}/search",
                json={"query": query, "limit": limit},
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
    except Exception as e:
        logger.warning(f"RAG query failed: {e}")
        return []
