"""Regressão: processamento incremental remove docs deletados do corpus.

Sem a poda, nós/textos de documentos removidos persistiriam para sempre nos
outputs cacheados de norm-analyzer e domain-analyzer.
"""
import json
from pathlib import Path

from pipeline.agents.domain_analyzer import DomainAnalyzerAgent
from pipeline.agents.norm_analyzer import NormAnalyzerAgent


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_norm_analyzer_prunes_removed_docs(tmp_path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()

    # estado anterior: docs A e B já processados
    _write(intermediate / "norm_analyzer.json", {
        "byDocument": {
            "doc-a": {"nodes": [{"id": "norma:doc-a"}], "artCount": 0},
            "doc-b": {"nodes": [{"id": "norma:doc-b"}], "artCount": 0},
        },
        "processedDocIds": {"doc-a": "hash-a", "doc-b": "hash-b"},
    })
    _write(intermediate / "corpus_texts_builder.json", {
        "texts": {
            "disp:doc-a:art1": {"textoCompleto": "x"},
            "disp:doc-b:art1": {"textoCompleto": "y"},
        },
    })
    # manifest atual: doc-b foi removido do corpus; doc-a inalterado (cache)
    _write(intermediate / "scan_manifest.json", {
        "documents": [
            {"documentId": "doc-a", "fileHash": "hash-a", "parsedPath": "corpus/parsed/doc-a.md"},
        ],
    })

    NormAnalyzerAgent().run(intermediate, corpus_dir)

    out = json.loads((intermediate / "norm_analyzer.json").read_text(encoding="utf-8"))
    assert "doc-b" not in out["byDocument"]
    assert "doc-b" not in out["processedDocIds"]
    assert all(n["id"] != "norma:doc-b" for doc in out["byDocument"].values() for n in doc["nodes"])

    texts = json.loads((intermediate / "corpus_texts_builder.json").read_text(encoding="utf-8"))["texts"]
    assert "disp:doc-b:art1" not in texts
    assert "disp:doc-a:art1" in texts


def test_domain_analyzer_drops_nodes_of_removed_docs(tmp_path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()

    # norm-analyzer atual conhece apenas doc-a (doc-b removido)
    _write(intermediate / "norm_analyzer.json", {
        "byDocument": {"doc-a": {"nodes": []}},
        "processedDocIds": {"doc-a": "hash-a"},
    })
    _write(intermediate / "scan_manifest.json", {"documents": []})
    # output anterior do domain-analyzer com nós/arestas de doc-a e doc-b
    _write(intermediate / "domain_analyzer.json", {
        "nodes": [
            {"id": "def:doc-a:pix", "sourceDoc": "doc-a"},
            {"id": "def:doc-b:spi", "sourceDoc": "doc-b"},
        ],
        "edges": [
            {"id": "disp:doc-a:art1--define--def:doc-a:pix", "source": "disp:doc-a:art1"},
            {"id": "disp:doc-b:art1--define--def:doc-b:spi", "source": "disp:doc-b:art1"},
        ],
        "processedDocIds": {"doc-a": "hash-a", "doc-b": "hash-b"},
    })

    DomainAnalyzerAgent().run(intermediate, corpus_dir)

    out = json.loads((intermediate / "domain_analyzer.json").read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in out["nodes"]}
    assert "def:doc-a:pix" in node_ids
    assert "def:doc-b:spi" not in node_ids
    edge_ids = {e["id"] for e in out["edges"]}
    assert "disp:doc-b:art1--define--def:doc-b:spi" not in edge_ids
    assert "doc-b" not in out["processedDocIds"]
