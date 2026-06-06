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
    from datetime import datetime
    graph = {
        "generatedAt": datetime.now().isoformat(),
        "corpus": "test",
        "nodes": [{
            "id": "norma:resolucao-bcb-001-2020",
            "type": "norma",
            "name": "Resolução BCB 001",
            "summary": "Regulamento Pix",
            "tags": [],
            "normativeLayer": "resolucao",
            "sourceDocument": "resolucao-bcb-001-2020",
            "review_required": False,
            "vigenciaMeta": {
                "dataInicio": "2020-11-12",
                "status": "vigente",
                "ultimaVerificacao": "2026-01-01",
            },
        }],
        "edges": [],
        "layers": [],
        "tours": [],
    }
    (tmp_path / "output" / "knowledge-graph.json").write_text(json.dumps(graph))

    import api.main as main_mod
    main_mod.OUTPUT_DIR = tmp_path / "output"

    resp = client.get("/api/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "links" in data  # D3 format
    assert data["nodes"][0]["id"] == "norma:resolucao-bcb-001-2020"


# ── GET /api/runs ─────────────────────────────────────────────────────────────

def test_runs_empty(client):
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert resp.json()["runs"] == []


def test_run_creates_pipeline_run_record(client, monkeypatch):
    client.post("/api/corpus/upload",
        files=[("files", ("resolucao-bcb-001-2020.pdf", io.BytesIO(b"%PDF"), "application/pdf"))])

    import api.main as main_mod
    monkeypatch.setattr(main_mod, "start_run", lambda run_id: None)

    client.post("/api/run")

    runs = client.get("/api/runs").json()["runs"]
    assert len(runs) == 1
    assert runs[0]["status"] == "running"
    assert runs[0]["id"] is not None


def test_run_creates_registry_json(client, tmp_path, monkeypatch):
    """POST /api/run deve exportar registry.json antes de iniciar o pipeline."""
    client.post("/api/corpus/upload",
        files=[("files", ("circular-bcb-3952-2019.pdf", io.BytesIO(b"%PDF"), "application/pdf"))])

    import api.main as main_mod
    monkeypatch.setattr(main_mod, "start_run", lambda run_id: None)

    client.post("/api/run")

    registry_path = tmp_path / "corpus" / "registry.json"
    assert registry_path.exists()
    registry = json.loads(registry_path.read_text())
    assert "circular-bcb-3952-2019" in registry


# ── _to_d3 unit tests ─────────────────────────────────────────────────────────

def test_to_d3_basic_conversion():
    from api.main import _to_d3
    data = {
        "nodes": [{
            "id": "norma:res-001",
            "type": "norma",
            "name": "Resolução 001",
            "summary": "Resumo",
            "tags": ["pix"],
            "normativeLayer": "resolucao",
            "review_required": False,
            "vigenciaMeta": {"status": "vigente"},
        }],
        "edges": [{
            "id": "e1",
            "source": "norma:res-001",
            "target": "norma:res-002",
            "type": "regulamenta",
            "weight": 0.8,
            "implicit": False,
            "deprecated": False,
        }],
    }
    result = _to_d3(data)

    assert "nodes" in result and "links" in result
    assert result["nodes"][0]["id"] == "norma:res-001"
    assert result["nodes"][0]["label"] == "Resolução 001"
    assert result["nodes"][0]["status"] == "vigente"
    assert result["links"][0]["source"] == "norma:res-001"
    assert result["links"][0]["type"] == "regulamenta"


def test_to_d3_normalizes_enum_status():
    from api.main import _to_d3
    data = {
        "nodes": [{
            "id": "n1", "type": "norma", "name": "N",
            "summary": "", "tags": [],
            "vigenciaMeta": {"status": "VigencyStatus.revogado"},
        }],
        "edges": [],
    }
    result = _to_d3(data)
    assert result["nodes"][0]["status"] == "revogado"


def test_to_d3_normalizes_enum_edge_type():
    from api.main import _to_d3
    data = {
        "nodes": [],
        "edges": [{
            "id": "e1", "source": "a", "target": "b",
            "type": "EdgeType.revoga_expressamente",
            "weight": 1.0, "implicit": False,
        }],
    }
    result = _to_d3(data)
    assert result["links"][0]["type"] == "revoga_expressamente"


def test_to_d3_filters_deprecated_edges():
    from api.main import _to_d3
    data = {
        "nodes": [],
        "edges": [
            {"id": "e1", "source": "a", "target": "b", "type": "altera", "weight": 1.0, "implicit": False, "deprecated": True},
            {"id": "e2", "source": "c", "target": "d", "type": "altera", "weight": 1.0, "implicit": False, "deprecated": False},
        ],
    }
    result = _to_d3(data)
    assert len(result["links"]) == 1
    assert result["links"][0]["id"] == "e2"


def test_to_d3_truncates_long_labels():
    from api.main import _to_d3
    long_name = "A" * 100
    data = {
        "nodes": [{"id": "n1", "type": "artigo", "name": long_name, "summary": "", "tags": [], "vigenciaMeta": {"status": "vigente"}}],
        "edges": [],
    }
    result = _to_d3(data)
    assert len(result["nodes"][0]["label"]) <= 60


# ── db/models.to_registry_dict ────────────────────────────────────────────────

def test_corpus_document_to_registry_dict():
    from db.models import CorpusDocument
    doc = CorpusDocument(
        id="resolucao-bcb-001-2020",
        authority="BCB",
        type="resolucao",
        number="1",
        year=2020,
        data_publicacao="2020-11-12",
        data_vigor="2020-11-16",
        vigency_status="vigente",
        description="Regulamento Pix",
    )
    d = doc.to_registry_dict()
    assert d["authority"] == "BCB"
    assert d["dataPublicacao"] == "2020-11-12"
    assert d["dataVigor"] == "2020-11-16"
    assert d["vigencyStatus"] == "vigente"
    assert "id" not in d  # id não vai para o registry
