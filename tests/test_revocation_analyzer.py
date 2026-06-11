"""Regressão: atribuição do artigo-fonte no revocation-analyzer.

O artigo que contém a sentença de revogação é a fonte da aresta — inclusive
quando a sentença abre com o próprio cabeçalho ("Art. 5º Fica revogado...")
e quando a mesma sentença aparece em mais de um artigo.
"""
import json
from pathlib import Path

from pipeline.agents.revocation_analyzer import RevocationAnalyzerAgent


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
                "number": "99",
                "year": 2020,
                "dataVigor": "2020-11-16",
            }
        ]
    }
    (intermediate / "scan_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (intermediate / "norm_analyzer.json").write_text(json.dumps({"byDocument": {}}), encoding="utf-8")
    return intermediate, corpus_dir


def _edges(intermediate: Path) -> list[dict]:
    out = json.loads((intermediate / "revocation_analyzer.json").read_text(encoding="utf-8"))
    return out["edges"]


def test_source_is_the_enclosing_article(tmp_path):
    text = (
        "Art. 1º Define os termos deste regulamento.\n\n"
        "Art. 5º Fica revogado o art. 2º da Resolução BCB nº 99, de 2020.\n"
    )
    intermediate, corpus_dir = _setup(tmp_path, text)
    RevocationAnalyzerAgent().run(intermediate, corpus_dir)

    edges = _edges(intermediate)
    assert len(edges) == 1
    # a fonte é o art. 5º (que contém a sentença), não o art. 1º anterior
    assert edges[0]["source"] == "disp:doc-a:art5"
    assert edges[0]["target"] == "disp:doc-a:art2"


def test_duplicate_sentences_attribute_each_enclosing_article(tmp_path):
    text = (
        "Art. 4º Fica revogado o art. 2º da Resolução BCB nº 99, de 2020.\n\n"
        "Art. 7º Fica revogado o art. 2º da Resolução BCB nº 99, de 2020.\n"
    )
    intermediate, corpus_dir = _setup(tmp_path, text)
    RevocationAnalyzerAgent().run(intermediate, corpus_dir)

    sources = {e["source"] for e in _edges(intermediate)}
    assert sources == {"disp:doc-a:art4", "disp:doc-a:art7"}


def test_revocation_before_any_article_falls_back(tmp_path):
    text = "Fica revogado o art. 2º da Resolução BCB nº 99, de 2020.\n"
    intermediate, corpus_dir = _setup(tmp_path, text)
    RevocationAnalyzerAgent().run(intermediate, corpus_dir)

    edges = _edges(intermediate)
    assert len(edges) == 1
    assert edges[0]["source"] == "disp:doc-a:disposicoesfinais"
