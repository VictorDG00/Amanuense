"""Regressão: REMETE_A no hierarchy-analyzer não inventa artigo-fonte.

Referência cruzada sem artigo identificável (ex.: preâmbulo) não vira aresta;
com artigo enclosing, a aresta sai do artigo correto.
"""
import json
from pathlib import Path

from pipeline.agents.hierarchy_analyzer import HierarchyAnalyzerAgent


def _setup(tmp_path: Path, text: str) -> tuple[Path, Path]:
    corpus_dir = tmp_path / "corpus"
    parsed = corpus_dir / "parsed"
    parsed.mkdir(parents=True)
    (parsed / "doc-a.md").write_text(text, encoding="utf-8")

    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    manifest = {
        "documents": [
            {
                "documentId": "doc-a",
                "parsedPath": "corpus/parsed/doc-a.md",
                "type": "resolucao",
                "number": "5",
                "year": 2021,
            },
            {
                "documentId": "doc-b",
                "parsedPath": "corpus/parsed/doc-b.md",
                "type": "resolucao",
                "number": "9",
                "year": 2020,
            },
        ]
    }
    (intermediate / "scan_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (intermediate / "norm_analyzer.json").write_text(json.dumps({"byDocument": {}}), encoding="utf-8")
    return intermediate, corpus_dir


def _remete_edges(intermediate: Path) -> list[dict]:
    out = json.loads((intermediate / "hierarchy_analyzer.json").read_text(encoding="utf-8"))
    return [e for e in out["edges"] if e["type"] == "remete_a"]


def test_cross_ref_without_enclosing_article_is_skipped(tmp_path):
    text = "Considerando o disposto no art. 3º da Resolução BCB nº 9, de 2020, resolve-se.\n"
    intermediate, corpus_dir = _setup(tmp_path, text)
    HierarchyAnalyzerAgent().run(intermediate, corpus_dir)
    assert _remete_edges(intermediate) == []


def test_cross_ref_uses_enclosing_article_as_source(tmp_path):
    text = "Art. 2º Aplica-se o disposto no art. 3º da Resolução BCB nº 9, de 2020.\n"
    intermediate, corpus_dir = _setup(tmp_path, text)
    HierarchyAnalyzerAgent().run(intermediate, corpus_dir)

    edges = _remete_edges(intermediate)
    assert len(edges) == 1
    assert edges[0]["source"] == "disp:doc-a:art2"
    assert edges[0]["target"] == "disp:doc-b:art3"
