"""NUMA Capture Web — FastAPI server.

Endpoints:
  POST   /api/sessions              — create a new session
  GET    /api/sessions              — list all sessions
  GET    /api/sessions/:id          — get session state
  POST   /api/sessions/:id/start    — start the interview
  POST   /api/sessions/:id/answer   — submit an answer, get next question
  GET    /api/sessions/:id/chat     — get conversation history
  GET    /api/sessions/:id/export   — export session as JSON
  GET    /api/phases                — get phase definitions
  GET    /health                    — health check
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from database import KnowledgeItem, Message, Session, get_db, init_db
from llm import (
    PHASE_DEFINITIONS,
    PHASE_ORDER,
    generate_next_question,
    generate_summary,
    get_next_template_prompt,
)
from rag_integration import index_knowledge_items, query_existing_docs as query_rag

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("numa-capture-web")


# ─── Models ─────────────────────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    expert_name: str = ""
    expert_role: str = ""
    domain: str = ""
    organization: str = ""


class AnswerRequest(BaseModel):
    answer: str


class StartRequest(BaseModel):
    pass  # no special params needed


# ─── App setup ──────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="NUMA Capture Web", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Helper ─────────────────────────────────────────────────────────────────


def _session_to_dict(session: Session) -> dict[str, Any]:
    """Convert a DB session to the API response format."""
    data = session.to_dict()
    data["messages"] = [m.to_dict() for m in session.messages]
    data["knowledge_items"] = [k.to_dict() for k in session.knowledge_items]
    data["current_phase_name"] = PHASE_DEFINITIONS.get(
        session.current_phase, {}
    ).get("name", "")
    return data


def _build_conversation(session: Session) -> list[dict[str, str]]:
    """Build the conversation list for LLM context."""
    return [
        {"role": m.role, "content": m.content} for m in session.messages
    ]


# ─── Endpoints ──────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "service": "numa-capture-web", "version": "1.0.0"}


@app.get("/api/phases")
async def get_phases():
    """Return all phase definitions."""
    return {
        "phases": {
            k: {
                "name": v["name"],
                "duration": v["duration"],
                "description": v["description"],
                "order": PHASE_ORDER.index(k) + 1,
                "tags": v["tags"],
            }
            for k, v in PHASE_DEFINITIONS.items()
        },
        "phase_order": PHASE_ORDER,
    }


@app.post("/api/sessions", status_code=201)
async def create_session(req: CreateSessionRequest, db: DBSession = Depends(get_db)):
    """Create a new interview session."""
    session = Session(
        expert_name=req.expert_name,
        expert_role=req.expert_role,
        domain=req.domain,
        organization=req.organization,
        status="pending",
        current_phase="A",
        phase_order=0,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    logger.info(f"Session created: {session.id} ({req.expert_name})")
    return _session_to_dict(session)


@app.get("/api/sessions")
async def list_sessions(db: DBSession = Depends(get_db)):
    """List all sessions."""
    sessions = db.query(Session).order_by(Session.created_at.desc()).all()
    return {"sessions": [s.to_dict() for s in sessions]}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, db: DBSession = Depends(get_db)):
    """Get full session state with messages and knowledge items."""
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    return _session_to_dict(session)


@app.post("/api/sessions/{session_id}/start")
async def start_interview(
    session_id: str, _req: StartRequest, db: DBSession = Depends(get_db)
):
    """Start the interview — sends the opening question of Phase A."""
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    if session.status == "completed":
        raise HTTPException(400, "Session already completed")

    session.status = "in_progress"
    session.current_phase = "A"
    session.phase_order = 0

    # Phase A opening
    phase_def = PHASE_DEFINITIONS["A"]
    question = phase_def["opening"]

    msg = Message(
        session_id=session.id,
        role="assistant",
        content=question,
        phase="A",
        order=0,
        tags="opening",
    )
    db.add(msg)
    db.commit()
    db.refresh(session)

    return _session_to_dict(session)


@app.post("/api/sessions/{session_id}/answer")
async def submit_answer(
    session_id: str, req: AnswerRequest, db: DBSession = Depends(get_db)
):
    """Submit an answer and get the next question.

    If the phase is complete, advances to the next phase.
    If all phases are done, marks the session as completed.
    """
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    if session.status == "completed":
        raise HTTPException(400, "Session already completed")

    # Save the user's answer
    user_msg = Message(
        session_id=session.id,
        role="user",
        content=req.answer,
        phase=session.current_phase,
        order=session.phase_order,
        tags="",
    )
    db.add(user_msg)
    db.commit()

    # Increment question counter
    session.phase_order += 1
    phase = session.current_phase
    phase_def = PHASE_DEFINITIONS.get(phase)

    # Check if phase is complete (3-4 questions per phase)
    max_questions = 1 + len(phase_def["prompts"]) if phase_def else 4
    phase_complete = session.phase_order >= max_questions

    if phase_complete:
        # Advance to next phase
        current_idx = PHASE_ORDER.index(phase)
        if current_idx + 1 < len(PHASE_ORDER):
            next_phase = PHASE_ORDER[current_idx + 1]
            session.current_phase = next_phase
            session.phase_order = 0
            next_phase_def = PHASE_DEFINITIONS[next_phase]

            # Send phase transition
            transition_msg = (
                f"✅ **Fase {phase} completada.** "
                f"Pasamos a la siguiente.\n\n"
                f"---\n\n"
                f"## 📋 Fase {next_phase}: {next_phase_def['name']}\n\n"
                f"{next_phase_def['description']}\n\n"
                f"_{next_phase_def['duration']}_\n\n"
                f"{next_phase_def['opening']}"
            )
            msg = Message(
                session_id=session.id,
                role="assistant",
                content=transition_msg,
                phase=next_phase,
                order=0,
                tags=f"phase_transition,{next_phase}",
            )
            db.add(msg)
        else:
            # All phases complete!
            session.status = "completed"
            session.completed_at = datetime.now(timezone.utc)

            # Generate summary
            conversation = _build_conversation(session)
            all_items = [k.to_dict() for k in session.knowledge_items]
            summary = await generate_summary(
                session.to_dict(),
                conversation,
                all_items,
            )

            completion_msg = (
                f"🎉 **¡Entrevista completada!**\n\n"
                f"Has completado las 4 fases de captura NUMA.\n\n"
                f"**Resumen:**\n{summary}\n\n"
                f"El conocimiento capturado se ha guardado y está siendo indexado."
            )
            msg = Message(
                session_id=session.id,
                role="assistant",
                content=completion_msg,
                phase="D",
                order=99,
                tags="completion",
            )
            db.add(msg)

            # Auto-index to RAG server
            await index_knowledge_items(
                session.to_dict(),
                all_items,
                conversation,
            )

    else:
        # Generate next question for the same phase
        session_data = session.to_dict()
        conversation = _build_conversation(session)

        next_question = await generate_next_question(session_data, conversation)
        if not next_question:
            next_question = get_next_template_prompt(session_data)
            if not next_question:
                next_question = "Cuéntame más sobre eso."

        msg = Message(
            session_id=session.id,
            role="assistant",
            content=next_question,
            phase=session.current_phase,
            order=session.phase_order,
            tags="",
        )
        db.add(msg)

    db.commit()
    db.refresh(session)

    return _session_to_dict(session)


@app.get("/api/sessions/{session_id}/chat")
async def get_chat_history(session_id: str, db: DBSession = Depends(get_db)):
    """Get the full conversation history."""
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    return {
        "session_id": session.id,
        "status": session.status,
        "current_phase": session.current_phase,
        "messages": [m.to_dict() for m in session.messages],
    }


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: str, db: DBSession = Depends(get_db)):
    """Export the session in NUMA Capture JSON format."""
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")

    export = {
        "protocol": "NUMA Capture v1.0",
        "session_id": session.id,
        "expert": {
            "name": session.expert_name,
            "role": session.expert_role,
            "domain": session.domain,
            "organization": session.organization,
        },
        "status": session.status,
        "phases_completed": session.current_phase,
        "duration_minutes": sum(
            int(PHASE_DEFINITIONS.get(p, {}).get("duration", "0").split()[0])
            for p in PHASE_ORDER[: PHASE_ORDER.index(session.current_phase) + 1]
        ),
        "knowledge_items": [k.to_dict() for k in session.knowledge_items],
        "conversation": [
            {
                "role": m.role,
                "phase": m.phase,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in session.messages
        ],
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }

    return export


@app.get("/api/sessions/{session_id}/progress")
async def get_progress(session_id: str, db: DBSession = Depends(get_db)):
    """Get progress per phase."""
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")

    phases = []
    for p in PHASE_ORDER:
        phase_def = PHASE_DEFINITIONS[p]
        phase_msgs = [m for m in session.messages if m.phase == p]
        max_q = 1 + len(phase_def["prompts"])
        answered = len([m for m in phase_msgs if m.role == "user"])
        completed = answered >= max_q or PHASE_ORDER.index(p) < PHASE_ORDER.index(session.current_phase)
        phases.append({
            "phase": p,
            "name": phase_def["name"],
            "total_questions": max_q,
            "answered": answered,
            "complete": completed,
            "is_active": p == session.current_phase and session.status == "in_progress",
        })

    return {
        "session_id": session.id,
        "status": session.status,
        "phases": phases,
    }


# ─── Main ───────────────────────────────────────────────────────────────────


# ─── Serve frontend (catch-all after API routes) ──────────

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
INDEX_HTML = os.path.join(FRONTEND_DIR, "index.html")


@app.get("/")
async def serve_index():
    """Serve the frontend app."""
    return HTMLResponse(content=open(INDEX_HTML).read())


@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Serve frontend static files or fallback to index.html."""
    # Prevent directory traversal
    if ".." in full_path or full_path.startswith("/"):
        return HTMLResponse(content=open(INDEX_HTML).read())

    file_path = os.path.join(FRONTEND_DIR, full_path)
    if os.path.isfile(file_path) and os.path.realpath(file_path).startswith(os.path.realpath(FRONTEND_DIR)):
        return HTMLResponse(content=open(file_path).read())
    return HTMLResponse(content=open(INDEX_HTML).read())


def serve():
    """Run the server with uvicorn."""
    import uvicorn

    host = os.environ.get("NUMA_HOST", "0.0.0.0")
    port = int(os.environ.get("NUMA_PORT", "8765"))
    uvicorn.run("server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    serve()
