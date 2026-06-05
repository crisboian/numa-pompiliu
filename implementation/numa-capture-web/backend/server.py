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

from database import (
    IndustrialEntity,
    IndustrialRelation,
    KnowledgeItem,
    Message,
    Session,
    ShadowEntry,
    get_db,
    init_db,
)
from llm import (
    PHASE_DEFINITIONS,
    PHASE_ORDER,
    analyze_answer,
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

# ─── Auth middleware ─────────────────────────────────────────
NUMA_API_KEY = os.environ.get("NUMA_API_KEY", "")
PUBLIC_PATHS = {"/health", "/", "/capture", "/capture.html", "/api/phases"}


@app.middleware("http")
async def auth_middleware(request, call_next):
    """Require X-API-Key header on all endpoints except public ones."""
    if not NUMA_API_KEY:
        # No key configured — all access allowed (dev mode)
        return await call_next(request)

    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/favicon"):
        return await call_next(request)

    api_key = request.headers.get("X-API-Key", "")
    if api_key != NUMA_API_KEY:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized — provide X-API-Key header"},
        )

    return await call_next(request)


cors_origins = os.environ.get("NUMA_CORS_ORIGINS", "*")
is_wildcard = cors_origins == "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins.split(",") if not is_wildcard else ["*"],
    allow_credentials=not is_wildcard,
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

    # Extract knowledge items from the answer
    session_data = session.to_dict()
    conversation = _build_conversation(session)
    try:
        analysis = await analyze_answer(session_data, conversation)
        for ki in analysis.get("knowledge_items", []):
            item = KnowledgeItem(
                session_id=session.id,
                statement=ki.get("statement", ""),
                category=ki.get("category", "fact"),
                weight=ki.get("weight", 0.5),
                phase=session.current_phase,
                rationale=ki.get("rationale", ""),
                conditions=json.dumps(ki.get("conditions", [])),
            )
            db.add(item)
        db.commit()
    except Exception as e:
        logger.warning(f"Knowledge extraction failed (non-fatal): {e}")

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
                f"Has completado las 5 fases de captura NUMA.\n\n"
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


# ─── Shadowing endpoints ────────────────────────────────────────────────────


@app.post("/api/shadow", status_code=201)
async def capture_shadow(req: dict, db: DBSession = Depends(get_db)):
    """Capture a quick shadow entry (<30 seconds)."""
    entry = ShadowEntry(
        session_id=req.get("session_id") or None,
        expert_name=req.get("expert_name", ""),
        content=req.get("content", ""),
        category=req.get("category", "decision"),
        context=req.get("context", ""),
        tags=req.get("tags", ""),
        source="quick",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info(f"Shadow entry #{entry.id} captured ({req.get('category')})")
    return {"status": "ok", "entry": entry.to_dict()}


@app.get("/api/shadow")
async def list_shadow(limit: int = 50, db: DBSession = Depends(get_db)):
    """List recent shadow entries."""
    entries = (
        db.query(ShadowEntry)
        .order_by(ShadowEntry.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"entries": [e.to_dict() for e in entries]}


@app.get("/api/shadow/stats")
async def shadow_stats(db: DBSession = Depends(get_db)):
    """Get shadow capture statistics."""
    from datetime import date

    today = date.today()
    all_entries = db.query(ShadowEntry).all()
    today_entries = [
        e for e in all_entries if e.created_at and e.created_at.date() == today
    ]
    categories: dict[str, int] = {}
    for e in all_entries:
        categories[e.category] = categories.get(e.category, 0) + 1
    latest = sorted(
        all_entries, key=lambda e: e.created_at or datetime.min, reverse=True
    )[:10]
    return {
        "today": len(today_entries),
        "total": len(all_entries),
        "categories": categories,
        "latest": [e.to_dict() for e in latest],
    }


# ─── Industrial Graph endpoints ─────────────────────────────────────────────


@app.post("/api/industrial/entities", status_code=201)
async def create_industrial_entity(
    req: dict, db: DBSession = Depends(get_db)
):
    """Add an entity to the industrial knowledge graph."""
    entity = IndustrialEntity(
        entity_type=req.get("entity_type", ""),
        name=req.get("name", ""),
        description=req.get("description", ""),
        attributes=req.get("attributes", "{}"),
        session_id=req.get("session_id") or None,
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    logger.info(f"Industrial entity #{entity.id}: {req.get('entity_type')}/{req.get('name')}")
    return {"status": "ok", "entity": entity.to_dict()}


@app.post("/api/industrial/relations", status_code=201)
async def create_industrial_relation(
    req: dict, db: DBSession = Depends(get_db)
):
    """Add a relation between two industrial entities."""
    src = (
        db.query(IndustrialEntity)
        .filter(IndustrialEntity.id == req.get("source_id"))
        .first()
    )
    tgt = (
        db.query(IndustrialEntity)
        .filter(IndustrialEntity.id == req.get("target_id"))
        .first()
    )
    if not src or not tgt:
        raise HTTPException(404, "Source or target entity not found")
    relation = IndustrialRelation(
        source_id=req.get("source_id"),
        target_id=req.get("target_id"),
        relation_type=req.get("relation_type", ""),
        weight=req.get("weight", 1.0),
        notes=req.get("notes", ""),
    )
    db.add(relation)
    db.commit()
    db.refresh(relation)
    return {"status": "ok", "relation": relation.to_dict()}


@app.get("/api/industrial/entities")
async def list_industrial_entities(
    entity_type: str = "",
    search: str = "",
    db: DBSession = Depends(get_db),
):
    """List industrial entities."""
    query = db.query(IndustrialEntity)
    if entity_type:
        query = query.filter(IndustrialEntity.entity_type == entity_type)
    if search:
        query = query.filter(IndustrialEntity.name.ilike(f"%{search}%"))
    entities = query.order_by(IndustrialEntity.name).all()
    return {"entities": [e.to_dict() for e in entities], "count": len(entities)}


@app.get("/api/industrial/entities/{entity_id}")
async def get_industrial_entity(entity_id: int, db: DBSession = Depends(get_db)):
    """Get an industrial entity with its relations."""
    entity = (
        db.query(IndustrialEntity).filter(IndustrialEntity.id == entity_id).first()
    )
    if not entity:
        raise HTTPException(404, "Entity not found")
    outbound = (
        db.query(IndustrialRelation)
        .filter(IndustrialRelation.source_id == entity_id)
        .all()
    )
    inbound = (
        db.query(IndustrialRelation)
        .filter(IndustrialRelation.target_id == entity_id)
        .all()
    )
    return {
        "entity": entity.to_dict(),
        "relations": {
            "outbound": [
                {
                    **r.to_dict(),
                    "target_name": db.query(IndustrialEntity.name)
                    .filter(IndustrialEntity.id == r.target_id)
                    .scalar(),
                }
                for r in outbound
            ],
            "inbound": [
                {
                    **r.to_dict(),
                    "source_name": db.query(IndustrialEntity.name)
                    .filter(IndustrialEntity.id == r.source_id)
                    .scalar(),
                }
                for r in inbound
            ],
        },
    }


@app.get("/api/industrial/graph")
async def get_industrial_graph(db: DBSession = Depends(get_db)):
    """Get full industrial graph for visualization."""
    entities = db.query(IndustrialEntity).all()
    relations = db.query(IndustrialRelation).all()
    return {
        "entities": [e.to_dict() for e in entities],
        "relations": [r.to_dict() for r in relations],
    }


@app.get("/api/industrial/types")
async def get_industrial_types(db: DBSession = Depends(get_db)):
    """Get entity/relation type counts."""
    from sqlalchemy import func

    entity_counts = (
        db.query(IndustrialEntity.entity_type, func.count(IndustrialEntity.id))
        .group_by(IndustrialEntity.entity_type)
        .all()
    )
    relation_counts = (
        db.query(IndustrialRelation.relation_type, func.count(IndustrialRelation.id))
        .group_by(IndustrialRelation.relation_type)
        .all()
    )
    return {
        "entity_types": [{"type": t, "count": c} for t, c in entity_counts],
        "relation_types": [{"type": t, "count": c} for t, c in relation_counts],
    }


# ─── Main ───────────────────────────────────────────────────────────────────
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


@app.get("/")
async def serve_landing():
    """Serve the NUMA landing page."""
    path = os.path.join(FRONTEND_DIR, "index.html")
    return HTMLResponse(content=open(path).read())


@app.get("/capture")
@app.get("/capture.html")
async def serve_capture():
    """Serve the NUMA Capture interview tool."""
    path = os.path.join(FRONTEND_DIR, "capture.html")
    return HTMLResponse(content=open(path).read())


@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Serve frontend static files or fallback to index.html."""
    # Return 404 for undefined API routes
    if full_path.startswith("api/"):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    # Prevent path traversal
    if ".." in full_path or full_path.startswith("/"):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "Invalid path"})
    file_path = os.path.join(FRONTEND_DIR, full_path)
    real_root = os.path.realpath(FRONTEND_DIR)
    real_path = os.path.realpath(file_path)
    if os.path.isfile(file_path) and real_path.startswith(real_root):
        with open(file_path) as f:
            return HTMLResponse(content=f.read())
    with open(os.path.join(FRONTEND_DIR, "index.html")) as f:
        return HTMLResponse(content=f.read())


def serve():
    """Run the server with uvicorn."""
    import uvicorn

    host = os.environ.get("NUMA_HOST", "0.0.0.0")
    port = int(os.environ.get("NUMA_PORT", "8765"))
    uvicorn.run("server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    serve()
