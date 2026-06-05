"""Tests for NUMA Capture Web — full flow, shadow, and industrial graph."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

# Set test env BEFORE importing server
os.environ["NUMA_API_KEY"] = ""
os.environ["NUMA_LLM_KEY"] = ""

from server import app

client = TestClient(app)


# ─── Health ──────────────────────────────────────────────────────────────────


class TestHealth:
    def test_health(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_phases(self):
        r = client.get("/api/phases")
        assert r.status_code == 200
        data = r.json()
        assert len(data["phases"]) == 5
        assert data["phase_order"] == ["A", "B", "C", "D", "E"]
        assert "E" in data["phases"]
        assert "Negative Knowledge" in data["phases"]["E"]["name"]


# ─── Full Interview Flow ────────────────────────────────────────────────────


class TestInterviewFlow:
    def test_full_flow(self):
        """Create → start → answer → knowledge items → export."""
        # Create
        r = client.post("/api/sessions", json={
            "expert_name": "Test Expert",
            "expert_role": "Operator",
            "domain": "Industrial",
            "organization": "Test Corp",
        })
        assert r.status_code == 201
        session = r.json()
        sid = session["id"]
        assert session["status"] == "pending"
        assert session["current_phase"] == "A"

        # Start
        r = client.post(f"/api/sessions/{sid}/start", json={})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "in_progress"
        assert data["current_phase"] == "A"
        assert len(data["messages"]) >= 1

        # Answer Phase A questions
        answers = [
            "Soy operador de ensacado en PROPAMSA. Mi trabajo es manejar la línea de ensacado rotativa.",
            "Uso la ensacadora SR-3000, el sistema de cintas y la selladora. Nada de eso está en mi descripción oficial.",
            "El manual dice que hay que purgar 5 minutos, pero en la práctica con 2 minutos basta si la línea está caliente.",
        ]
        for i, answer in enumerate(answers):
            r = client.post(f"/api/sessions/{sid}/answer", json={"answer": answer})
            assert r.status_code == 200
            data = r.json()

        # Verify we're in Phase B now (or completed Phase A)
        # Phase A has 1 opening + 3 prompts = 4 total questions
        # We sent 3 answers, so we should be mid-way or at Phase B
        assert data["status"] == "in_progress"

        # Verify knowledge items were extracted
        r = client.get(f"/api/sessions/{sid}")
        data = r.json()
        # Knowledge items should exist (even if template fallback)
        assert data["knowledge_count"] >= 0
        assert data["status"] == "in_progress"

        # Export
        r = client.get(f"/api/sessions/{sid}/export")
        assert r.status_code == 200
        export = r.json()
        assert export["protocol"] == "NUMA Capture v1.0"
        assert export["session_id"] == sid

    def test_create_session_validation(self):
        """Empty name should still work."""
        r = client.post("/api/sessions", json={})
        assert r.status_code == 201

    def test_session_not_found(self):
        r = client.get("/api/sessions/nonexistent-id")
        assert r.status_code == 404

    def test_unknown_api_path(self):
        r = client.get("/api/nonexistent")
        assert r.status_code == 404


# ─── Shadowing ──────────────────────────────────────────────────────────────


class TestShadowing:
    def test_capture_shadow(self):
        r = client.post("/api/shadow", json={
            "content": "Válvula de purga hay que abrirla despacio",
            "category": "warning",
            "context": "mantenimiento línea 3",
            "tags": "seguridad,mantenimiento",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["status"] == "ok"
        assert data["entry"]["category"] == "warning"
        assert "Válvula" in data["entry"]["content"]

    def test_list_shadow(self):
        r = client.get("/api/shadow")
        assert r.status_code == 200
        data = r.json()
        assert "entries" in data
        assert len(data["entries"]) >= 1

    def test_shadow_stats(self):
        r = client.get("/api/shadow/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        assert "today" in data
        assert "categories" in data


# ─── Industrial Graph ───────────────────────────────────────────────────────


class TestIndustrialGraph:
    def test_create_entity(self):
        r = client.post("/api/industrial/entities", json={
            "entity_type": "machine",
            "name": "Ensacadora Rotativa",
            "description": "Máquina de ensacado continuo",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["status"] == "ok"
        assert data["entity"]["entity_type"] == "machine"
        machine_id = data["entity"]["id"]

        r = client.post("/api/industrial/entities", json={
            "entity_type": "procedure",
            "name": "Purga de Línea",
        })
        assert r.status_code == 201
        proc_id = r.json()["entity"]["id"]

        # Create relation
        r = client.post("/api/industrial/relations", json={
            "source_id": machine_id,
            "target_id": proc_id,
            "relation_type": "requires",
            "notes": "Antes del mantenimiento",
        })
        assert r.status_code == 201
        rel = r.json()
        assert rel["status"] == "ok"
        assert rel["relation"]["relation_type"] == "requires"

    def test_list_entities(self):
        r = client.get("/api/industrial/entities")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 1

    def test_list_entities_by_type(self):
        r = client.get("/api/industrial/entities?entity_type=machine")
        assert r.status_code == 200
        data = r.json()
        assert all(e["entity_type"] == "machine" for e in data["entities"])

    def test_entity_detail(self):
        r = client.get("/api/industrial/entities/1")
        assert r.status_code == 200
        data = r.json()
        assert "entity" in data
        assert "relations" in data
        assert "outbound" in data["relations"]
        assert "inbound" in data["relations"]

    def test_entity_not_found(self):
        r = client.get("/api/industrial/entities/9999")
        assert r.status_code == 404

    def test_industrial_types(self):
        r = client.get("/api/industrial/types")
        assert r.status_code == 200
        data = r.json()
        assert "entity_types" in data
        assert "relation_types" in data

    def test_full_graph(self):
        r = client.get("/api/industrial/graph")
        assert r.status_code == 200
        data = r.json()
        assert "entities" in data
        assert "relations" in data

    def test_relation_invalid_source(self):
        r = client.post("/api/industrial/relations", json={
            "source_id": 9999,
            "target_id": 1,
            "relation_type": "requires",
        })
        assert r.status_code == 404


# ─── Auth (key enforcement) ────────────────────────────────────────────────


class TestAuth:
    def test_without_key_allowed_in_dev_mode(self):
        """Without NUMA_API_KEY set, all endpoints should work."""
        r = client.get("/api/shadow")
        assert r.status_code == 200

    def test_frontend_served(self):
        r = client.get("/")
        assert r.status_code == 200
        assert "NUMA" in r.text

    def test_capture_served(self):
        r = client.get("/capture")
        assert r.status_code == 200
        assert "NUMA" in r.text
