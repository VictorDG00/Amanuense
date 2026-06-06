import io
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool

from db.models import Base
from db.session import get_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient com DB in-memory e CORPUS/OUTPUT apontando para tmp_path."""
    import pipeline.config as cfg
    monkeypatch.setattr(cfg, "CORPUS_DIR", tmp_path / "corpus")
    monkeypatch.setattr(cfg, "OUTPUT_DIR", tmp_path / "output")
    (tmp_path / "corpus" / "raw").mkdir(parents=True)
    (tmp_path / "output").mkdir()

    # StaticPool mantém uma única conexão — essencial para SQLite in-memory entre requests
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    from api.main import app
    import api.main as main_mod
    monkeypatch.setattr(main_mod, "CORPUS_DIR", tmp_path / "corpus")
    monkeypatch.setattr(main_mod, "OUTPUT_DIR", tmp_path / "output")
    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app, raise_server_exceptions=True)

    app.dependency_overrides.clear()


# ── GET /api/corpus ───────────────────────────────────────────────────────────

def test_corpus_empty(client):
    resp = client.get("/api/corpus")
    assert resp.status_code == 200
    assert resp.json()["documents"] == []


# ── POST /api/corpus/upload ───────────────────────────────────────────────────

def test_upload_single_pdf(client):
    resp = client.post(
        "/api/corpus/upload",
        files=[("files", ("resolucao-bcb-001-2020.pdf", io.BytesIO(b"%PDF fake"), "application/pdf"))],
    )
    assert resp.status_code == 200
    added = resp.json()["added"]
    assert len(added) == 1
    assert added[0]["id"] == "resolucao-bcb-001-2020"
    assert added[0]["type"] == "resolucao"
    assert added[0]["authority"] == "BCB"
    assert added[0]["year"] == 2020


def test_upload_multiple_pdfs(client):
    files = [
        ("files", ("resolucao-bcb-001-2020.pdf", io.BytesIO(b"%PDF r"), "application/pdf")),
        ("files", ("circular-bcb-3952-2019.pdf", io.BytesIO(b"%PDF c"), "application/pdf")),
    ]
    resp = client.post("/api/corpus/upload", files=files)
    assert resp.status_code == 200
    assert len(resp.json()["added"]) == 2


def test_upload_appears_in_list(client):
    client.post("/api/corpus/upload",
        files=[("files", ("circular-bcb-3952-2019.pdf", io.BytesIO(b"%PDF"), "application/pdf"))])
    docs = client.get("/api/corpus").json()["documents"]
    assert any(d["id"] == "circular-bcb-3952-2019" for d in docs)


def test_upload_manual(client):
    resp = client.post("/api/corpus/upload",
        files=[("files", ("manual-seguranca-pix.pdf", io.BytesIO(b"%PDF"), "application/pdf"))])
    added = resp.json()["added"]
    assert added[0]["type"] == "manual"


def test_upload_idempotent(client):
    """Re-uploading the same doc updates it rather than duplicating."""
    for _ in range(2):
        client.post("/api/corpus/upload",
            files=[("files", ("resolucao-bcb-001-2020.pdf", io.BytesIO(b"%PDF"), "application/pdf"))])
    docs = client.get("/api/corpus").json()["documents"]
    assert len([d for d in docs if d["id"] == "resolucao-bcb-001-2020"]) == 1


# ── DELETE /api/corpus/{doc_id} ───────────────────────────────────────────────

def test_delete_existing(client):
    client.post("/api/corpus/upload",
        files=[("files", ("resolucao-bcb-001-2020.pdf", io.BytesIO(b"%PDF"), "application/pdf"))])
    resp = client.delete("/api/corpus/resolucao-bcb-001-2020")
    assert resp.status_code == 200
    docs = client.get("/api/corpus").json()["documents"]
    assert docs == []


def test_delete_nonexistent(client):
    resp = client.delete("/api/corpus/doc-que-nao-existe")
    assert resp.status_code == 404


# ── POST /api/run ─────────────────────────────────────────────────────────────

def test_run_empty_corpus_returns_400(client):
    resp = client.post("/api/run")
    assert resp.status_code == 400


def test_run_with_corpus_returns_run_id(client, monkeypatch):
    # Upload a doc first
    client.post("/api/corpus/upload",
        files=[("files", ("resolucao-bcb-001-2020.pdf", io.BytesIO(b"%PDF"), "application/pdf"))])

    # Mock start_run so we don't actually launch the pipeline
    import api.main as main_mod
    monkeypatch.setattr(main_mod, "start_run", lambda run_id: None)

    resp = client.post("/api/run")
    assert resp.status_code == 200
    assert "run_id" in resp.json()


# ── GET /api/graph ────────────────────────────────────────────────────────────

def test_graph_not_found(client):
    resp = client.get("/api/graph")
    assert resp.status_code == 404


def test_graph_returns_data(client, tmp_path):
    graph = {"nodes": [{"id": "n1"}], "links": [], "layers": [], "tours": []}
    (tmp_path / "output" / "knowledge-graph.json").write_text(json.dumps(graph))

    import api.main as main_mod
    main_mod.OUTPUT_DIR = tmp_path / "output"

    resp = client.get("/api/graph")
    assert resp.status_code == 200
    assert resp.json()["nodes"][0]["id"] == "n1"


# ── GET /api/runs ─────────────────────────────────────────────────────────────

def test_runs_empty(client):
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert resp.json()["runs"] == []
