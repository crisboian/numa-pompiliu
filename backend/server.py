"""NUMA Capture Web — FastAPI server.
All endpoints use proper Pydantic models, async DB, and structured responses.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any
from dotenv import load_dotenv
load_dotenv()


from fastapi import Depends, FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi import Request
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import (
    IndustrialEntity,
    IndustrialRelation,
    KnowledgeItem,
    Message,
    SafetyReport,
    Session,
    ShadowEntry,
    get_db,
    get_session_with_data,
    init_db,
)
from enums import EntityType, MessageRole, Phase, PHASE_ORDER, RelationType
from llm import (
    PHASE_DEFINITIONS,
    analyze_answer,
    generate_next_question,
    generate_summary,
    get_next_template_prompt,
)
from middleware import rate_limiter, setup_middleware
from auth import require_auth, setup_auth as setup_auth_oauth
from stripe_integration import check_report_access, setup_stripe as setup_stripe_payments
from rag_integration import index_knowledge_items

# ─── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("numa-capture-web")

# ─── Pydantic models ────────────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    expert_name: str = Field(default="", max_length=255)
    expert_role: str = Field(default="", max_length=255)
    domain: str = Field(default="", max_length=255)
    organization: str = Field(default="", max_length=255)


class AnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=50000)


class StartRequest(BaseModel):
    pass


class ShadowCaptureRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=36)
    expert_name: str = Field(default="", max_length=255)
    content: str = Field(..., min_length=1, max_length=5000)
    category: str = Field(default="decision", max_length=64)
    context: str = Field(default="", max_length=512)
    tags: str = Field(default="", max_length=512)

    @field_validator("category")
    @classmethod
    def valid_shadow_category(cls, v: str) -> str:
        valid = {"decision", "observation", "tip", "warning"}
        if v not in valid:
            raise ValueError(f"category must be one of {valid}")
        return v


class CreateEntityRequest(BaseModel):
    entity_type: str = Field(..., max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=10000)
    attributes: str = Field(default="{}", max_length=10000)
    session_id: str | None = Field(default=None, max_length=36)

    @field_validator("entity_type")
    @classmethod
    def valid_entity_type(cls, v: str) -> str:
        valid = {e.value for e in EntityType}
        if v not in valid:
            raise ValueError(f"entity_type must be one of {valid}")
        return v


class CreateRelationRequest(BaseModel):
    source_id: int = Field(..., gt=0)
    target_id: int = Field(..., gt=0)
    relation_type: str = Field(..., max_length=64)
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    notes: str = Field(default="", max_length=10000)

    @field_validator("relation_type")
    @classmethod
    def valid_relation_type(cls, v: str) -> str:
        valid = {r.value for r in RelationType}
        if v not in valid:
            raise ValueError(f"relation_type must be one of {valid}")
        return v


# ─── App setup ──────────────────────────────────────────────────────────────


# ─── ChromaDB RAG ──────────────────────────────────────────────────────────

CHROMA_DIR = os.path.join(os.path.dirname(__file__), "..", "numa_rag_index")
_rag_collection: Any = None
_rag_model: Any = None


def _load_rag() -> tuple[Any, Any]:
    """Load ChromaDB collection + embedding model (lazy, thread-safe)."""
    global _rag_collection, _rag_model
    if _rag_collection is not None:
        return _rag_model, _rag_collection
    import chromadb
    from chromadb.config import Settings
    from sentence_transformers import SentenceTransformer

    if not os.path.isdir(CHROMA_DIR):
        logger.warning("RAG index not found at %s", CHROMA_DIR)
        return None, None
    try:
        client = chromadb.PersistentClient(
            path=CHROMA_DIR, settings=Settings(anonymized_telemetry=False))
        try:
            _rag_collection = client.get_collection("numa_knowledge")
        except Exception:
            _rag_collection = client.create_collection("numa_knowledge")
            logger.info("Created new ChromaDB collection 'numa_knowledge'")
        _rag_model = SentenceTransformer("all-MiniLM-L6-v2")
        count = _rag_collection.count()
        logger.info("RAG index loaded: %d documents (%s)", count, CHROMA_DIR)
    except Exception as exc:
        logger.warning("RAG load failed: %s", exc)
        return None, None
    return _rag_model, _rag_collection


def _index_items_to_chroma(items: list[dict]) -> int:
    """Index knowledge items into local ChromaDB for RAG search.
    Each item must have: id, content, category, weight, phase.
    Returns number of items indexed.
    """
    model, coll = _load_rag()
    if model is None or coll is None:
        logger.warning("ChromaDB not available for indexing")
        return 0

    indexed = 0
    for item in items:
        try:
            meta = {
                "item_id": str(item.get("id", indexed)),
                "category": item.get("category", "fact"),
                "weight": str(item.get("weight", 0.5)),
                "phase": item.get("phase", "A"),
            }
            emb = model.encode(item.get("content", "")).tolist()
            coll.add(
                embeddings=[emb],
                documents=[item.get("content", "")],
                metadatas=[meta],
                ids=[f"item_{item.get('id', indexed)}_{indexed}"],
            )
            indexed += 1
        except Exception as e:
            logger.warning("Failed to index item #%s: %s", item.get("id"), e)
    if indexed:
        logger.info("Indexed %d items into local ChromaDB", indexed)
    return indexed


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized (async SQLite)")
    # Warm up RAG index (lazy — does nothing on import)
    _rag_collection
    yield


app = FastAPI(
    title="NUMA Capture Web",
    version="2.0.0",
    lifespan=lifespan,
    # Structured error responses
    exception_handlers={
        404: lambda req, exc: JSONResponse(
            status_code=404,
            content={"error": "not_found", "detail": exc.detail or "Resource not found"},
        ),
        400: lambda req, exc: JSONResponse(
            status_code=400,
            content={"error": "bad_request", "detail": exc.detail or "Bad request"},
        ),
    },
)

# ─── Auth ───────────────────────────────────────────────────────────────────

# Paths that bypass auth entirely:
# - landing/health/static for marketing pages
# - /api/phases is read-only public catalog data
# - /api/stripe/webhook is called by Stripe; authentication is the HMAC signature
# - /auth/* runs the OAuth login flow (must be reachable while logged out)
PUBLIC_PATHS = {"/health", "/", "/api/phases", "/api/stripe/webhook"}
PUBLIC_PREFIXES = ("/favicon", "/static/", "/auth/", "/paper/")


@app.middleware("http")
async def auth_middleware(request, call_next):
    from auth import get_session_user

    path = request.url.path

    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)

    # Every /api/* call (other than the explicit allow-list above) requires a
    # signed session cookie. This protects destructive endpoints like
    # POST /api/rag/reindex/all from anonymous callers.
    if path.startswith("/api/"):
        user = get_session_user(request)
        if not user:
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "detail": "Authentication required"},
            )
        return await call_next(request)

    # Non-API paths (HTML pages, etc.) fall through; individual handlers
    # decide whether to redirect to login.
    return await call_next(request)


# ─── CORS ───────────────────────────────────────────────────────────────────

cors_origins = os.environ.get("NUMA_CORS_ORIGINS", "*")
is_wildcard = cors_origins == "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins.split(",") if not is_wildcard else ["*"],
    allow_credentials=not is_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionMiddleware, secret_key=os.environ.get("NUMA_SESSION_SECRET", "numa-session-secret-dev-only"))
# Register security/rate-limit middleware (after CORS, before auth)
setup_middleware(app)

# Initialize OAuth and Stripe
setup_auth_oauth(app)
setup_stripe_payments(app)

# ─── Helpers ────────────────────────────────────────────────────────────────


def _session_to_dict(session: Session) -> dict[str, Any]:
    data = session.to_dict()
    data["messages"] = [m.to_dict() for m in (session.messages or [])]
    data["knowledge_items"] = [k.to_dict() for k in (session.knowledge_items or [])]
    phase = session.current_phase or ""
    data["current_phase_name"] = Phase(phase).name_ if phase in {"A", "B", "C", "D", "E"} else ""
    return data


def _build_conversation(session: Session) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in session.messages]


# ─── Endpoints ──────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "numa-capture-web",
        "version": "2.0.0",
        "rate_limiter": rate_limiter.stats,
    }


@app.get("/api/phases")
async def get_phases():
    return {
        "phases": {
            k: {
                "name": v["name"],
                "duration": v["duration"],
                "description": v["description"],
                "order": Phase(k).order + 1,
                "tags": v["tags"],
                "color": Phase(k).color,
            }
            for k, v in PHASE_DEFINITIONS.items()
        },
        "phase_order": [p.value for p in PHASE_ORDER],
    }


@app.post("/api/sessions", status_code=201)
async def create_session(
    req: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
):
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
    await db.commit()
    # Re-fetch with relationships loaded
    session = await get_session_with_data(db, session.id)
    logger.info("Session created: %s (%s)", session.id, req.expert_name)
    return _session_to_dict(session)


@app.get("/api/sessions")
async def list_sessions(
    user: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session)
        .options(selectinload(Session.messages), selectinload(Session.knowledge_items))
        .order_by(Session.created_at.desc())
    )
    sessions = result.scalars().all()
    return {"sessions": [s.to_dict() for s in sessions]}


@app.get("/api/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    session = await get_session_with_data(db, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return _session_to_dict(session)


@app.post("/api/sessions/{session_id}/start")
async def start_interview(
    session_id: str,
    _req: StartRequest,
    db: AsyncSession = Depends(get_db),
):
    session = await get_session_with_data(db, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.status == "completed":
        raise HTTPException(400, "Session already completed")

    session.status = "in_progress"
    session.current_phase = "A"
    session.phase_order = 0

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
    await db.commit()
    await db.refresh(session, attribute_names=["messages"])
    return _session_to_dict(session)


@app.post("/api/sessions/{session_id}/answer")
async def submit_answer(
    session_id: str,
    req: AnswerRequest,
    db: AsyncSession = Depends(get_db),
):
    session = await get_session_with_data(db, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.status == "completed":
        raise HTTPException(400, "Session already completed")

    # Save user answer
    user_msg = Message(
        session_id=session.id,
        role="user",
        content=req.answer,
        phase=session.current_phase,
        order=session.phase_order,
        tags="",
    )
    db.add(user_msg)
    await db.commit()
    # Refresh messages relationship so conversation includes the new answer
    await db.refresh(session, attribute_names=["messages"])

    # Extract knowledge items
    conversation = _build_conversation(session)
    try:
        analysis = await analyze_answer(session.to_dict(), conversation)
        chroma_items = []
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
            # Collect for ChromaDB indexing (id will be assigned after commit)
            chroma_items.append({
                "content": ki.get("statement", ""),
                "category": ki.get("category", "fact"),
                "weight": ki.get("weight", 0.5),
                "phase": session.current_phase or "A",
            })
        await db.commit()
        # Re-fetch items to get their DB-assigned IDs
        if chroma_items:
            try:
                # Query the last N items for this session to get real IDs
                result = await db.execute(
                    select(KnowledgeItem)
                    .where(KnowledgeItem.session_id == session.id)
                    .order_by(KnowledgeItem.id.desc())
                    .limit(len(chroma_items))
                )
                db_items = result.scalars().all()
                for idx, db_item in enumerate(db_items):
                    chroma_items[idx]["id"] = db_item.id
                _index_items_to_chroma(chroma_items)
            except Exception as e2:
                logger.warning("ChromaDB indexing after answer failed: %s", e2)
    except Exception as e:
        logger.warning("Knowledge extraction failed (non-fatal): %s", e)

    session.phase_order += 1
    phase = session.current_phase
    phase_def = PHASE_DEFINITIONS.get(phase)

    max_questions = 1 + len(phase_def["prompts"]) if phase_def else 4
    phase_complete = session.phase_order >= max_questions

    if phase_complete:
        current_idx = PHASE_ORDER.index(Phase(phase))
        if current_idx + 1 < len(PHASE_ORDER):
            next_phase = PHASE_ORDER[current_idx + 1]
            session.current_phase = next_phase.value
            session.phase_order = 0
            next_phase_def = PHASE_DEFINITIONS[next_phase.value]

            transition_msg = (
                f"✅ **Fase {phase} completada.** "
                f"Pasamos a la siguiente.\n\n---\n\n"
                f"## 📋 Fase {next_phase.value}: {next_phase_def['name']}\n\n"
                f"{next_phase_def['description']}\n\n_{next_phase_def['duration']}_\n\n"
                f"{next_phase_def['opening']}"
            )
            msg = Message(
                session_id=session.id,
                role="assistant",
                content=transition_msg,
                phase=next_phase.value,
                order=0,
                tags=f"phase_transition,{next_phase.value}",
            )
            db.add(msg)
        else:
            session.status = "completed"
            session.completed_at = datetime.now(timezone.utc)

            conversation = _build_conversation(session)
            all_items = [k.to_dict() for k in session.knowledge_items]
            summary = await generate_summary(
                session.to_dict(), conversation, all_items
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
            # Index to local ChromaDB (also keeps the external RAG call for compat)
            try:
                _index_items_to_chroma([
                    {
                        "id": k.get("id", k.get("statement", "")[:20]),
                        "content": k.get("statement", k.get("content", "")),
                        "category": k.get("category", "fact"),
                        "weight": k.get("weight", 0.5),
                        "phase": k.get("phase", session.current_phase or "A"),
                    }
                    for k in all_items
                ])
            except Exception as e:
                logger.warning("Chroma completion indexing failed: %s", e)
            await index_knowledge_items(
                session.to_dict(), all_items, conversation
            )
    else:
        session_data = session.to_dict()
        conversation = _build_conversation(session)
        next_question = await generate_next_question(session_data, conversation)
        if not next_question:
            next_question = get_next_template_prompt(session_data) or "Cuéntame más sobre eso."

        msg = Message(
            session_id=session.id,
            role="assistant",
            content=next_question,
            phase=session.current_phase,
            order=session.phase_order,
            tags="",
        )
        db.add(msg)

    await db.commit()
    await db.refresh(session, attribute_names=["messages", "knowledge_items"])
    return _session_to_dict(session)


@app.get("/api/sessions/{session_id}/chat")
async def get_chat_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    session = await get_session_with_data(db, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return {
        "session_id": session.id,
        "status": session.status,
        "current_phase": session.current_phase,
        "messages": [m.to_dict() for m in session.messages],
    }


@app.get("/api/sessions/{session_id}/export")
async def export_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    session = await get_session_with_data(db, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    duration_minutes = 0
    for p in PHASE_ORDER[: PHASE_ORDER.index(Phase(session.current_phase)) + 1]:
        dur_str = PHASE_DEFINITIONS.get(p.value, {}).get("duration", "0 min")
        try:
            duration_minutes += int(dur_str.split()[0])
        except (ValueError, IndexError):
            pass

    export = {
        "protocol": "NUMA Capture v2.0",
        "session_id": session.id,
        "expert": {
            "name": session.expert_name,
            "role": session.expert_role,
            "domain": session.domain,
            "organization": session.organization,
        },
        "status": session.status,
        "phases_completed": session.current_phase,
        "duration_minutes": duration_minutes,
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
async def get_progress(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    session = await get_session_with_data(db, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    phases = []
    for p in PHASE_ORDER:
        pv = p.value
        phase_def = PHASE_DEFINITIONS[pv]
        phase_msgs = [m for m in session.messages if m.phase == pv]
        max_q = 1 + len(phase_def["prompts"])
        answered = len([m for m in phase_msgs if m.role == "user"])
        completed = (
            answered >= max_q
            or PHASE_ORDER.index(p) < PHASE_ORDER.index(Phase(session.current_phase))
        )
        phases.append({
            "phase": pv,
            "name": phase_def["name"],
            "total_questions": max_q,
            "answered": answered,
            "complete": completed,
            "is_active": pv == session.current_phase and session.status == "in_progress",
        })

    return {"session_id": session.id, "status": session.status, "phases": phases}


# ─── Shadow endpoints ──────────────────────────────────────────────────────


@app.post("/api/shadow", status_code=201)
async def capture_shadow(
    req: ShadowCaptureRequest,
    db: AsyncSession = Depends(get_db),
):
    entry = ShadowEntry(
        session_id=req.session_id,
        expert_name=req.expert_name,
        content=req.content,
        category=req.category,
        context=req.context,
        tags=req.tags,
        source="quick",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    logger.info("Shadow entry #%d captured (%s)", entry.id, req.category)

    # Index into ChromaDB for RAG search
    try:
        _index_items_to_chroma([{
            "id": entry.id,
            "content": f"[Shadow] {req.content}",
            "category": req.category,
            "weight": 0.9,
            "phase": "S",
        }])
    except Exception as e:
        logger.warning("ChromaDB indexing for shadow failed: %s", e)

    return {"status": "ok", "entry": entry.to_dict()}


@app.get("/api/shadow")
async def list_shadow(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ShadowEntry)
        .order_by(ShadowEntry.created_at.desc())
        .limit(min(limit, 200))
    )
    entries = result.scalars().all()
    return {"entries": [e.to_dict() for e in entries]}


@app.get("/api/shadow/stats")
async def shadow_stats(
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    result = await db.execute(select(ShadowEntry))
    all_entries = result.scalars().all()

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



# ─── Reports endpoints (safety/security reports) ──────────────────────────


@app.post("/api/reports/upload", status_code=201)
async def upload_report(
    file: UploadFile = File(...),
    user: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Upload a safety report. NUMA does NOT store the file.
    Extracted text is saved as Gmail draft in user's inbox."""
    user_id = user.get("sub", "")
    token_info = user.get("token_info")
    user_email = user.get("email", "")
    if not user_id:
        raise HTTPException(401, "Not authenticated")
    ext = os.path.splitext(file.filename or "report")[1].lower()
    if ext not in (".pdf", ".txt", ".md"):
        raise HTTPException(400, "Only PDF, TXT, MD files supported")
    raw_bytes = await file.read()
    text_content = ""
    try:
        if ext == ".pdf":
            import subprocess, tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(raw_bytes); tmp_path = tmp.name
            try:
                result = subprocess.run(["pdftotext", tmp_path, "-"], capture_output=True, text=True, timeout=30)
                text_content = result.stdout.strip()
            finally:
                os.unlink(tmp_path)
        else:
            text_content = raw_bytes.decode("utf-8", errors="replace").strip()
    except Exception as e:
        logger.warning("Text extraction failed: %s", e)
    if len(text_content) > 50000:
        text_content = text_content[:50000] + "\n[...truncated]"
    draft_id = ""; gmail_err = ""
    if token_info and user_email:
        try:
            from gmail_client import create_gmail_draft
            subject = f"[NUMA] Report: {file.filename}"
            body = f"NUMA Safety Report - processed {datetime.now(timezone.utc).isoformat()}\n\nThis draft was created by NUMA Capture. The text was extracted from {file.filename}.\nIt lives in your Gmail - NUMA does not store it.\n\n{'='*50}\n\n{text_content[:30000]}"
            draft = create_gmail_draft(token_info, user_email, subject, body)
            draft_id = draft.get("id", "")
        except Exception as e:
            gmail_err = str(e)
    report = SafetyReport(
        user_id=user_id, original_filename=file.filename or "report",
        stored_filename="", gmail_draft_id=draft_id,
        file_size=len(raw_bytes), content_type=file.content_type or "application/octet-stream",
        text_content=text_content or "(empty)",
        status="uploaded" if draft_id else "stored_locally",
    )
    db.add(report); await db.commit(); await db.refresh(report)
    return {"status": "ok", "report": report.to_dict(), "note": "NUMA does not store your files. Data saved to your Gmail drafts.", "gmail_draft_id": draft_id or None, "gmail_error": gmail_err or None}


@app.get("/api/reports")
async def list_reports(user: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    user_id = user.get("sub", "")
    if not user_id:
        raise HTTPException(401, "Not authenticated")
    result = await db.execute(select(SafetyReport).where(SafetyReport.user_id == user_id).order_by(SafetyReport.created_at.desc()))
    return {"reports": [r.to_dict() for r in result.scalars().all()]}


@app.get("/api/reports/{report_id}")
async def get_report(report_id: int, user: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SafetyReport).where(SafetyReport.id == report_id, SafetyReport.user_id == user.get("sub", "")))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Report not found")
    d = report.to_dict(); d["text_content"] = report.text_content
    return {"report": d}


@app.post("/api/reports/{report_id}/process")
async def process_report(report_id: int, user: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SafetyReport).where(SafetyReport.id == report_id, SafetyReport.user_id == user.get("sub", "")))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Report not found")
    if not report.text_content or report.text_content in ("(empty)", "[Error extracting text]"):
        raise HTTPException(400, "Report has no extractable text")
    report.status = "processing"; await db.commit()
    try:
        from llm import analyze_report_text
        entities = await analyze_report_text(report.text_content)
        for ent in entities:
            db.add(IndustrialEntity(entity_type=ent.get("type","procedure"), name=ent.get("name","Unknown")[:255], description=ent.get("description","")[:10000]))
        report.status = "processed"; await db.commit()
        return {"status": "ok", "entities_count": len(entities)}
    except Exception as e:
        report.status = "error"; report.processing_error = str(e)[:512]; await db.commit()
        raise HTTPException(500, f"Processing failed: {e}")


@app.delete("/api/reports/{report_id}")
async def delete_report(report_id: int, user: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SafetyReport).where(SafetyReport.id == report_id, SafetyReport.user_id == user.get("sub", "")))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Report not found")
    await db.delete(report); await db.commit()
    return {"status": "ok", "deleted": report_id, "note": "Original data remains in your Gmail drafts."}


@app.get("/api/reports/samples")
async def get_sample_reports():
    return {"samples": [
        {"id":"sample_1","title":"Hopper Jam - Packing Line 3","language":"en",
         "text":"INCIDENT: Hopper Jam - Packing Line 3  Date: 2025-11-14  Equipment: H-2000 Rotary Packer\n\nHopper stopped feeding. Foreign object (polypropylene bag fragment) lodged between auger flights and hopper wall. E-stop activated. LOTO applied. Object removed.\n\nROOT CAUSE: Torn bulk bag loaded 2h prior. Fragment traveled through pneumatic system.\n\nACTIONS: Pre-load inspection checklist. Magnetic separator. Train operators.\n\nLESSON: Small tears let fragments travel through the entire system."},
        {"id":"sample_2","title":"Arc Flash Near-Miss - Substation B","language":"en",
         "text":"NEAR-MISS: Arc Flash - Substation B  Date: 2025-12-02  Equipment: 400V MCC-4\n\nNon-contact voltage tester failed to detect backup UPS feed. Small arc flash when screwdriver bridged live busbar to ground frame. Cat 2 PPE. No injuries.\n\nROOT CAUSE: Switching diagram only showed main feed. UPS backup undocumented.\n\nACTIONS: Update all MCC diagrams. Mandate contact voltmeters. Label backup feeds.\n\nRULE: Always verify zero energy with contact voltmeter."},
        {"id":"sample_3","title":"Atasco en Tolva - Linea 2","language":"es",
         "text":"INFORME: Atasco en Tolva - Linea 2  Fecha: 2025-10-28  Equipo: DV-300\n\nTolva dejo de caer material. Puente de 30cm de carbonato calcico apelmazado por humedad (linea parada 72h, trampilla abierta).\n\nCAUSA: Carbonato calcico higroscopico.\n\nACCIONES: Vaciar tolvas si parada >24h. Filtro desecante.\n\nLECCION: Trampilla abierta = riesgo con materiales higroscopicos."}
    ]}


@app.post("/api/reports/process-sample")
async def process_sample_report(body: dict, user: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    text = body.get("text", ""); title = body.get("title", "Sample")
    if not text or len(text) < 50:
        raise HTTPException(400, "Sample text too short")
    try:
        from llm import analyze_report_text
        entities = await analyze_report_text(text)
        for ent in entities:
            db.add(IndustrialEntity(entity_type=ent.get("type","procedure"), name=ent.get("name","Unknown")[:255], description=ent.get("description","")[:10000]))
        await db.commit()
        return {"status": "ok", "entities_count": len(entities), "entities": entities}
    except Exception as e:
        raise HTTPException(500, f"Processing failed: {e}")


# ─── Industrial Graph endpoints ────────────────────────────────────────────


@app.post("/api/industrial/entities", status_code=201)
async def create_industrial_entity(
    req: CreateEntityRequest,
    db: AsyncSession = Depends(get_db),
):
    entity = IndustrialEntity(
        entity_type=req.entity_type,
        name=req.name,
        description=req.description,
        attributes=req.attributes,
        session_id=req.session_id,
    )
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    logger.info(
        "Industrial entity #%d: %s/%s", entity.id, req.entity_type, req.name
    )
    return {"status": "ok", "entity": entity.to_dict()}


@app.post("/api/industrial/relations", status_code=201)
async def create_industrial_relation(
    req: CreateRelationRequest,
    db: AsyncSession = Depends(get_db),
):
    src_result = await db.execute(
        select(IndustrialEntity).where(IndustrialEntity.id == req.source_id)
    )
    src = src_result.scalar_one_or_none()
    tgt_result = await db.execute(
        select(IndustrialEntity).where(IndustrialEntity.id == req.target_id)
    )
    tgt = tgt_result.scalar_one_or_none()
    if not src or not tgt:
        raise HTTPException(404, "Source or target entity not found")
    relation = IndustrialRelation(
        source_id=req.source_id,
        target_id=req.target_id,
        relation_type=req.relation_type,
        weight=req.weight,
        notes=req.notes,
    )
    db.add(relation)
    await db.commit()
    await db.refresh(relation)
    return {"status": "ok", "relation": relation.to_dict()}


@app.get("/api/industrial/entities")
async def list_industrial_entities(
    entity_type: str = "",
    search: str = "",
    db: AsyncSession = Depends(get_db),
):
    stmt = select(IndustrialEntity).order_by(IndustrialEntity.name)
    if entity_type:
        stmt = stmt.where(IndustrialEntity.entity_type == entity_type)
    if search:
        stmt = stmt.where(IndustrialEntity.name.ilike(f"%{search}%"))
    result = await db.execute(stmt)
    entities = result.scalars().all()
    return {"entities": [e.to_dict() for e in entities], "count": len(entities)}


@app.get("/api/industrial/entities/{entity_id}")
async def get_industrial_entity(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(IndustrialEntity).where(IndustrialEntity.id == entity_id)
    )
    entity = result.scalar_one_or_none()
    if not entity:
        raise HTTPException(404, "Entity not found")

    outbound_result = await db.execute(
        select(IndustrialRelation).where(IndustrialRelation.source_id == entity_id)
    )
    outbound = outbound_result.scalars().all()

    inbound_result = await db.execute(
        select(IndustrialRelation).where(IndustrialRelation.target_id == entity_id)
    )
    inbound = inbound_result.scalars().all()

    # Attach names
    out_list = []
    for r in outbound:
        d = r.to_dict()
        tgt = await db.execute(
            select(IndustrialEntity.name).where(IndustrialEntity.id == r.target_id)
        )
        d["target_name"] = tgt.scalar()
        out_list.append(d)

    in_list = []
    for r in inbound:
        d = r.to_dict()
        src = await db.execute(
            select(IndustrialEntity.name).where(IndustrialEntity.id == r.source_id)
        )
        d["source_name"] = src.scalar()
        in_list.append(d)

    return {"entity": entity.to_dict(), "relations": {"outbound": out_list, "inbound": in_list}}


@app.get("/api/industrial/graph")
async def get_industrial_graph(
    db: AsyncSession = Depends(get_db),
):
    entities = (await db.execute(select(IndustrialEntity))).scalars().all()
    relations = (await db.execute(select(IndustrialRelation))).scalars().all()
    return {
        "entities": [e.to_dict() for e in entities],
        "relations": [r.to_dict() for r in relations],
    }


@app.get("/api/industrial/types")
async def get_industrial_types(
    db: AsyncSession = Depends(get_db),
):
    entity_result = await db.execute(
        select(IndustrialEntity.entity_type, func.count(IndustrialEntity.id))
        .group_by(IndustrialEntity.entity_type)
    )
    relation_result = await db.execute(
        select(IndustrialRelation.relation_type, func.count(IndustrialRelation.id))
        .group_by(IndustrialRelation.relation_type)
    )
    return {
        "entity_types": [{"type": t, "count": c} for t, c in entity_result.all()],
        "relation_types": [{"type": t, "count": c} for t, c in relation_result.all()],
    }



# ─── Comparativa (multi-expert comparison) ──────────────────────────────────


@app.get("/api/comparativa")
async def get_comparativa(
    domain: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Compare knowledge items across sessions, grouped by domain.

    Returns consensus, contradictions, unique items, and phase coverage.
    """
    stmt = (
        select(Session)
        .options(selectinload(Session.knowledge_items))
        .order_by(Session.created_at.desc())
    )
    if domain:
        stmt = stmt.where(Session.domain == domain)
    result = await db.execute(stmt)
    sessions_list: list[Session] = result.scalars().all()

    if not sessions_list:
        return {
            "domains": [],
            "total_sessions": 0,
            "total_domains": 0,
        }

    # Group sessions by domain
    from collections import defaultdict

    by_domain: dict[str, list[Session]] = defaultdict(list)
    for s in sessions_list:
        d = s.domain or "Sin dominio"
        by_domain[d].append(s)

    # ── helpers ──────────────────────────────────────────────────────────

    def _normalize(text: str) -> str:
        """Lowercase, strip punctuation, collapse whitespace."""
        import re

        t = text.lower().strip()
        t = re.sub(r"[^\w\sáéíóúñü]", "", t)
        t = re.sub(r"\s+", " ", t)
        return t[:120]

    def _negation_words(text: str) -> set[str]:
        """Words that suggest negation or contradiction."""
        neg = {
            "no", "nunca", "jamás", "evitar", "prohibido", "nadie",
            "ningún", "ninguna", "sin", "excepto", "salvo", "imposible",
            "nunca", "tampoco", "ni",
        }
        words = set(text.lower().split())
        return words & neg

    def _compare_statements(stmt_a: str, stmt_b: str) -> str:
        """Compare two statements and return relation type.

        Returns: 'same', 'contradiction', 'related', or 'different'
        """
        na = _normalize(stmt_a)
        nb = _normalize(stmt_b)
        if na == nb:
            return "same"
        # Check if one is contained in the other
        if len(na) > 10 and len(nb) > 10:
            if na in nb or nb in na:
                return "same"
        # Check word overlap
        wa = set(na.split())
        wb = set(nb.split())
        if len(wa) > 2 and len(wb) > 2:
            overlap = len(wa & wb) / max(len(wa), len(wb))
            if overlap > 0.7:
                return "related"
            if overlap > 0.35:
                # Check for negation-based contradiction
                nega = _negation_words(stmt_a)
                negb = _negation_words(stmt_b)
                shared = wa & wb
                if (
                    len(shared) >= 3
                    and (bool(nega) != bool(negb))
                ):
                    return "contradiction"
                if len(shared) >= 3:
                    return "related"
        return "different"

    # ── Process each domain ──────────────────────────────────────────────

    domain_results = []
    for d, sess_list in by_domain.items():
        # Gather all knowledge items per session
        session_items: dict[str, list[dict[str, Any]]] = {}
        for s in sess_list:
            session_items[s.id] = [
                {
                    "id": k.id,
                    "statement": k.statement,
                    "category": k.category,
                    "weight": k.weight,
                    "phase": k.phase,
                    "rationale": k.rationale,
                    "session_id": s.id,
                    "expert_name": s.expert_name,
                }
                for k in (s.knowledge_items or [])
            ]

        total_sessions = len(sess_list)
        threshold = max(2, total_sessions // 2)  # 50%+

        # ── Compare all pairs of items across sessions ──
        # Build item list with session info
        all_items_flat: list[dict[str, Any]] = []
        for sid, items in session_items.items():
            all_items_flat.extend(items)

        # Session-level summary
        session_summaries = []
        for s in sess_list:
            items = session_items.get(s.id, [])
            phase_counts: dict[str, int] = defaultdict(int)
            for it in items:
                phase_counts[it["phase"]] = phase_counts.get(it["phase"], 0) + 1
            session_summaries.append(
                {
                    "session_id": s.id,
                    "expert_name": s.expert_name,
                    "expert_role": s.expert_role,
                    "organization": s.organization,
                    "total_items": len(items),
                    "items_by_phase": dict(phase_counts),
                }
            )

        # ── Find consensus items ──
        # Group similar statements across sessions
        from collections import Counter

        consensus_groups: list[dict[str, Any]] = []
        used = set()
        for i, item_a in enumerate(all_items_flat):
            if item_a["id"] in used:
                continue
            group = [item_a]
            used.add(item_a["id"])
            for j, item_b in enumerate(all_items_flat):
                if item_b["id"] in used:
                    continue
                rel = _compare_statements(
                    item_a["statement"], item_b["statement"]
                )
                if rel in ("same", "related"):
                    group.append(item_b)
                    used.add(item_b["id"])
            # Count how many distinct sessions agree
            sessions_in_group = len({g["session_id"] for g in group})
            if sessions_in_group >= threshold and len(group) >= 2:
                consensus_groups.append(
                    {
                        "canonical_statement": item_a["statement"],
                        "session_count": sessions_in_group,
                        "total_sessions": total_sessions,
                        "items": group,
                    }
                )

        # ── Find contradictions ──
        contradictions_list: list[dict[str, Any]] = []
        for i, item_a in enumerate(all_items_flat):
            for j, item_b in enumerate(all_items_flat):
                if i >= j:
                    continue
                if item_a["session_id"] == item_b["session_id"]:
                    continue
                rel = _compare_statements(
                    item_a["statement"], item_b["statement"]
                )
                if rel == "contradiction":
                    contradictions_list.append(
                        {
                            "statement_a": item_a["statement"],
                            "session_a": item_a["expert_name"],
                            "session_a_id": item_a["session_id"],
                            "phase_a": item_a["phase"],
                            "statement_b": item_b["statement"],
                            "session_b": item_b["expert_name"],
                            "session_b_id": item_b["session_id"],
                            "phase_b": item_b["phase"],
                        }
                    )

        # Deduplicate contradictions (A-B vs B-A)
        seen_contra: set[tuple[int, int]] = set()
        deduped_contra = []
        for c in contradictions_list:
            pair = tuple(sorted([c["session_a_id"], c["session_b_id"]]))
            if pair not in seen_contra:
                seen_contra.add(pair)
                deduped_contra.append(c)
        contradictions_list = deduped_contra

        # ── Unique items per session ──
        unique_per_session: dict[str, list[dict]] = {}
        for sid, items in session_items.items():
            uniques = []
            for item_a in items:
                is_unique = True
                for other_sid, other_items in session_items.items():
                    if other_sid == sid:
                        continue
                    for item_b in other_items:
                        rel = _compare_statements(
                            item_a["statement"], item_b["statement"]
                        )
                        if rel in ("same", "related", "contradiction"):
                            is_unique = False
                            break
                    if not is_unique:
                        break
                if is_unique:
                    uniques.append(item_a)
            session_name = next(
                (s.expert_name for s in sess_list if s.id == sid), sid[:8]
            )
            unique_per_session[session_name] = uniques

        # ── Coverage by phase ──
        phases_order = ["A", "B", "C", "D", "E"]
        coverage_table: list[dict[str, Any]] = []
        for s in sess_list:
            items = session_items.get(s.id, [])
            phase_counts: dict[str, int] = defaultdict(int)
            for it in items:
                phase_counts[it["phase"]] += 1
            row = {
                "expert_name": s.expert_name,
                "session_id": s.id,
            }
            for p in phases_order:
                row[f"phase_{p}"] = phase_counts.get(p, 0)
            row["total"] = len(items)
            coverage_table.append(row)

        domain_results.append(
            {
                "domain": d,
                "total_sessions": total_sessions,
                "total_items": len(all_items_flat),
                "sessions": session_summaries,
                "consensus": consensus_groups,
                "consensus_count": len(consensus_groups),
                "contradictions": contradictions_list,
                "contradictions_count": len(contradictions_list),
                "unique_per_session": unique_per_session,
                "coverage": coverage_table,
            }
        )

    # ── Collect unique domains for filter ──
    all_domains = sorted({s.domain or "Sin dominio" for s in sessions_list})

    return {
        "domains": domain_results,
        "all_domains": all_domains,
        "total_sessions": len(sessions_list),
        "total_domains": len(by_domain),
        "total_consensus": sum(d["consensus_count"] for d in domain_results),
        "total_contradictions": sum(
            d["contradictions_count"] for d in domain_results
        ),
    }


# ─── RAG Search ────────────────────────────────────────────────────────────


async def graph_graph_search(query: str, db: AsyncSession) -> list[dict]:
    """Search industrial knowledge graph entities matching query terms.

    Tokenizes the query, searches IndustrialEntity.name and .description
    with case-insensitive LIKE, scores by match quality + relation count.
    """
    words = [w for w in query.replace("-", " ").replace("_", " ").split() if len(w) > 1]
    if not words:
        return []

    # Build OR conditions: each word matches name OR description
    conditions = []
    for w in words:
        pattern = f"%{w}%"
        conditions.append(IndustrialEntity.name.ilike(pattern))
        conditions.append(IndustrialEntity.description.ilike(pattern))

    stmt = select(IndustrialEntity).where(or_(*conditions)).order_by(IndustrialEntity.name)
    result = await db.execute(stmt)
    entities = result.scalars().all()

    if not entities:
        return []

    # For each matched entity, count inbound + outbound relations
    entity_ids = [e.id for e in entities]
    outbound_counts: dict[int, int] = {}
    inbound_counts: dict[int, int] = {}

    # Count outbound relations
    out_result = await db.execute(
        select(IndustrialRelation.source_id, func.count(IndustrialRelation.id))
        .where(IndustrialRelation.source_id.in_(entity_ids))
        .group_by(IndustrialRelation.source_id)
    )
    for sid, cnt in out_result.all():
        outbound_counts[sid] = cnt

    # Count inbound relations
    in_result = await db.execute(
        select(IndustrialRelation.target_id, func.count(IndustrialRelation.id))
        .where(IndustrialRelation.target_id.in_(entity_ids))
        .group_by(IndustrialRelation.target_id)
    )
    for tid, cnt in in_result.all():
        inbound_counts[tid] = cnt

    # Score each entity: base from match quality + bonus from relations
    items = []
    for entity in entities:
        name_lower = entity.name.lower()
        desc_lower = entity.description.lower()
        query_lower = query.lower()

        # Match quality: how many query words appear in name or description
        match_count = sum(1 for w in words if w.lower() in name_lower or w.lower() in desc_lower)
        best_matches = max(
            sum(1 for w in words if w.lower() in name_lower),
            sum(1 for w in words if w.lower() in desc_lower),
        )
        base_score = match_count / max(len(words), 1)

        # Boost if exact phrase match
        if query_lower in name_lower or query_lower in desc_lower:
            base_score += 0.3

        rel_count = outbound_counts.get(entity.id, 0) + inbound_counts.get(entity.id, 0)
        graph_score = round(base_score + min(rel_count * 0.1, 0.5), 4)

        items.append({
            "source": "graph",
            "id": entity.id,
            "category": entity.entity_type,
            "weight": 1.0,
            "phase": "-",
            "content": f"{entity.name}: {entity.description}",
            "score": graph_score,
        })

    # Sort by score descending
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


class RAGSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)


@app.post("/api/rag/search")
async def rag_search(
    req: RAGSearchRequest,
    db: AsyncSession = Depends(get_db),
):
    import time
    t0 = time.time()
    model, coll = _load_rag()

    # ── 1. RAG results (semantic) ──
    rag_items: list[dict] = []
    if model is not None and coll is not None:
        emb = model.encode(req.query).tolist()
        results = coll.query(query_embeddings=[emb], n_results=8)
        for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
            rag_items.append({
                "source": "rag",
                "id": int(meta["item_id"]),
                "category": meta["category"],
                "weight": float(meta["weight"]),
                "phase": meta["phase"],
                "content": doc,
                "score": round(1 - dist, 4),
            })

    # ── 2. Graph results (knowledge graph) ──
    graph_items = await graph_graph_search(req.query, db)

    # ── 3. RRF Fusion ──
    # RRF(item) = Σ 1/(60 + rank(source))  for each source that contains item
    K = 60

    # Build item_key -> {sources: {source: rank}, rrf_score}
    # Use (id, category, content) as composite key for dedup
    fused: dict[str, dict] = {}

    def add_items(items: list[dict], source: str):
        for rank, item in enumerate(items):
            key = f"{item['id']}|{item['category']}"
            if key not in fused:
                entry = {
                    "id": item["id"],
                    "category": item["category"],
                    "weight": item["weight"],
                    "phase": item["phase"],
                    "content": item["content"],
                    "sources": {},
                    "rrf_score": 0.0,
                    "rag_score": 0.0,
                    "graph_score": 0.0,
                }
                # Carry over best individual score per source
                fused[key] = entry

            fused[key]["sources"][source] = rank
            if source == "rag":
                fused[key]["rag_score"] = max(fused[key]["rag_score"], item["score"])
            else:
                fused[key]["graph_score"] = max(fused[key]["graph_score"], item["score"])

    add_items(rag_items, "rag")
    add_items(graph_items, "graph")

    # Compute RRF scores
    for entry in fused.values():
        total = 0.0
        for src, rank in entry["sources"].items():
            total += 1.0 / (K + rank)
        # Blend individual scores as tiebreaker
        best_rag = entry.pop("rag_score")
        best_graph = entry.pop("graph_score")
        blended = max(best_rag, best_graph)
        entry["rrf_score"] = round(total, 6)
        entry["score"] = blended
        entry["source"] = "+".join(sorted(entry.pop("sources").keys()))

    # Sort by RRF score descending, then by individual score descending
    result_items = sorted(fused.values(), key=lambda x: (-x["rrf_score"], -x["score"]))

    elapsed = round(time.time() - t0, 3)
    return {
        "query": req.query,
        "results": result_items,
        "count": len(result_items),
        "sources": {"rag": len(rag_items), "graph": len(graph_items)},
        "elapsed": elapsed,
    }


@app.get("/api/rag/stats")
async def rag_stats():
    _, coll = _load_rag()
    if coll is None:
        return {"count": 0, "status": "no_index"}
    return {"count": coll.count(), "status": "ready"}


@app.post("/api/rag/reindex")
async def rag_reindex(
    user: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    "# Reindex all knowledge items + shadow entries from DB into ChromaDB"
    model, coll = _load_rag()
    if model is None or coll is None:
        return {"status": "error", "reason": "ChromaDB not available"}

    # Get all knowledge items
    result = await db.execute(
        select(KnowledgeItem).order_by(KnowledgeItem.id)
    )
    items = result.scalars().all()

    chroma_items = []
    for item in items:
        chroma_items.append({
            "id": item.id,
            "content": item.statement or "",
            "category": item.category or "fact",
            "weight": item.weight or 0.5,
            "phase": item.phase or "A",
        })

    # Get all shadow entries
    result2 = await db.execute(
        select(ShadowEntry).order_by(ShadowEntry.id)
    )
    shadows = result2.scalars().all()
    for entry in shadows:
        chroma_items.append({
            "id": f"shadow_{entry.id}",
            "content": f"[Shadow] {entry.content}",
            "category": entry.category or "quick",
            "weight": 0.9,
            "phase": "S",
        })

    if not chroma_items:
        return {"status": "ok", "action": "nothing_to_index", "items": 0}

    indexed = _index_items_to_chroma(chroma_items)
    total = coll.count()
    return {
        "status": "ok",
        "action": "indexed",
        "items": indexed,
        "total_in_chroma": total,
    }


@app.post("/api/rag/reindex/all")
async def rag_reindex_all(
    user: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    "# Clear and rebuild ChromaDB from all DB knowledge items + shadow entries."
    import chromadb
    from chromadb.config import Settings

    ch_dir = CHROMA_DIR
    if os.path.isdir(ch_dir):
        import shutil
        shutil.rmtree(ch_dir)
        logger.info("Deleted existing ChromaDB index at %s", ch_dir)

    # Reset global so next load creates fresh index
    global _rag_collection, _rag_model
    _rag_collection = None
    _rag_model = None

    # Recreate dir so _load_rag can find it
    os.makedirs(ch_dir, exist_ok=True)

    # Re-init: creates fresh collection
    model, coll = _load_rag()
    if coll is None:
        return {"status": "error", "reason": "Failed to create fresh ChromaDB"}

    return await rag_reindex(db)


# ─── Serve frontend ─────────────────────────────────────────────────────────

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


PAPER_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "paper")


@app.get("/paper/{filename}")
async def serve_paper(filename: str):
    allowed = {"numa_paper.pdf", "numa_paper_v2.pdf", "numa_paper_es.pdf"}
    if filename not in allowed:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    from fastapi.responses import FileResponse
    path = os.path.join(PAPER_DIR, filename)
    return FileResponse(path, media_type="application/pdf")


@app.get("/")
async def serve_landing(request: Request):
    host = request.headers.get("host", "")
    filename = "index.es.html" if "numapompiliu.es" in host else "index.html"
    path = os.path.join(FRONTEND_DIR, filename)
    return HTMLResponse(content=open(path).read())


@app.get("/capture")
@app.get("/capture.html")
async def serve_capture(request: Request):
    from auth import get_session_user
    user = get_session_user(request)
    if not user:
        from starlette.responses import RedirectResponse
        resp = RedirectResponse(url="/auth/google/login", status_code=302)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    host = request.headers.get("host", "")
    is_es = "numapompiliu.es" in host
    filename = "capture.es.html" if is_es else "capture.html"
    path = os.path.join(FRONTEND_DIR, filename)

    # If not authenticated and on .es, redirect to .com where OAuth works
    if is_es and not user:
        from starlette.responses import RedirectResponse
        return RedirectResponse(url="https://numapompiliu.com/auth/google/login", status_code=302)

    return HTMLResponse(content=open(path).read())


@app.get("/security")
async def serve_security(request: Request):
    host = request.headers.get("host", "")
    is_es = "numapompiliu.es" in host
    filename = "security.es.html" if is_es else "security.html"
    path = os.path.join(FRONTEND_DIR, filename)
    return HTMLResponse(content=open(path).read())


# ─── Paid Report endpoint ──────────────────────────────────────────────────
#
# Stripe's success_url redirects the buyer's browser to /report/{session_id}.
# Access is gated by check_report_access() — i.e. a recorded paid purchase
# for this session_id — NOT by login cookie, because the redirect target must
# work from the Stripe checkout flow regardless of session state.
# Returns 402 Payment Required when no purchase is on record.

@app.get("/report/{session_id}")
async def get_report(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    purchase = check_report_access(session_id)
    if purchase is None:
        return JSONResponse(
            status_code=402,
            content={
                "error": "payment_required",
                "detail": "No paid purchase found for this session_id",
                "session_id": session_id,
            },
        )

    # Build report payload from the NUMA session if one exists for this id.
    # If session_id is a user-scoped id (no interview attached), we still
    # return the purchase info so the buyer sees confirmation of access.
    session = await get_session_with_data(db, session_id)
    report: dict[str, Any] = {
        "session_id": session_id,
        "purchase": purchase,
    }

    if session is not None:
        report["interview"] = {
            "expert": {
                "name": session.expert_name,
                "role": session.expert_role,
                "domain": session.domain,
                "organization": session.organization,
            },
            "status": session.status,
            "current_phase": session.current_phase,
            "knowledge_items": [k.to_dict() for k in (session.knowledge_items or [])],
            "messages": [m.to_dict() for m in (session.messages or [])],
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        }

    return report


@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": "API endpoint not found"})
    if ".." in full_path or full_path.startswith("/"):
        return JSONResponse(status_code=404, content={"error": "invalid_path", "detail": "Invalid path"})
    file_path = os.path.join(FRONTEND_DIR, full_path)
    real_root = os.path.realpath(FRONTEND_DIR)
    real_path = os.path.realpath(file_path)
    if os.path.isfile(file_path) and real_path.startswith(real_root):
        content_type = "application/octet-stream"
        if full_path.endswith(".js"):
            content_type = "application/javascript"
        elif full_path.endswith(".css"):
            content_type = "text/css"
        elif full_path.endswith(".json"):
            content_type = "application/json"
        elif full_path.endswith(".svg"):
            content_type = "image/svg+xml"
        elif full_path.endswith(".png"):
            content_type = "image/png"
        elif full_path.endswith(".ico"):
            content_type = "image/x-icon"
        from fastapi.responses import FileResponse
        return FileResponse(file_path, media_type=content_type)
    # Fallback to index.html for SPA
    return HTMLResponse(content=open(os.path.join(FRONTEND_DIR, "index.html")).read())


# ─── Main ───────────────────────────────────────────────────────────────────


def serve():
    import uvicorn
    host = os.environ.get("NUMA_HOST", "0.0.0.0")
    port = int(os.environ.get("NUMA_PORT", "8765"))
    uvicorn.run("server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    serve()
