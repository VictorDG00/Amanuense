import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pipeline.agents.corpus_scanner import _clean_text, _ensure_parsed, _pdf_to_markdown


# ── _clean_text ───────────────────────────────────────────────────────────────

def test_clean_text_collapses_blank_lines():
    text = "line1\n\n\n\n\nline2"
    assert _clean_text(text) == "line1\n\nline2"


def test_clean_text_fixes_hyphenated_linebreak():
    text = "regu-\nlamento"
    assert _clean_text(text) == "regulamento"


def test_clean_text_strips_edges():
    assert _clean_text("  \n\nhello\n\n  ") == "hello"


def test_clean_text_empty():
    assert _clean_text("") == ""


# ── _pdf_to_markdown ──────────────────────────────────────────────────────────

def test_pdf_to_markdown_uses_pdfplumber(tmp_path):
    fake_pdf = tmp_path / "doc.pdf"
    fake_pdf.write_bytes(b"fake")

    long_text = "Artigo 1 O participante direto " + "x" * 100
    mock_page = MagicMock()
    mock_page.extract_text.return_value = long_text
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]

    with patch("pdfplumber.open", return_value=mock_pdf):
        result = _pdf_to_markdown(fake_pdf)

    assert "Artigo 1" in result


def test_pdf_to_markdown_falls_back_to_pymupdf(tmp_path):
    fake_pdf = tmp_path / "doc.pdf"
    fake_pdf.write_bytes(b"fake")

    mock_page = MagicMock()
    mock_page.get_text.return_value = "Texto via pymupdf"
    mock_doc = MagicMock()
    mock_doc.__iter__ = lambda s: iter([mock_page])
    mock_doc.close = MagicMock()

    with patch("pdfplumber.open", side_effect=Exception("pdfplumber fail")):
        with patch("fitz.open", return_value=mock_doc):
            result = _pdf_to_markdown(fake_pdf)

    assert "Texto via pymupdf" in result


# ── _ensure_parsed ────────────────────────────────────────────────────────────

def test_ensure_parsed_already_exists(tmp_path):
    raw = tmp_path / "doc.pdf"
    raw.write_bytes(b"fake")
    parsed = tmp_path / "doc.md"
    parsed.write_text("conteúdo já parseado")

    result = _ensure_parsed(raw, parsed, "doc")

    assert result is True
    # Should not have overwritten
    assert parsed.read_text() == "conteúdo já parseado"


def test_ensure_parsed_converts_pdf(tmp_path):
    raw = tmp_path / "doc.pdf"
    raw.write_bytes(b"fake")
    parsed = tmp_path / "doc.md"

    with patch("pipeline.agents.corpus_scanner._pdf_to_markdown", return_value="A" * 200):
        result = _ensure_parsed(raw, parsed, "doc")

    assert result is True
    assert parsed.exists()
    assert "A" * 200 == parsed.read_text()


def test_ensure_parsed_returns_false_on_short_text(tmp_path):
    raw = tmp_path / "doc.pdf"
    raw.write_bytes(b"fake")
    parsed = tmp_path / "doc.md"

    with patch("pipeline.agents.corpus_scanner._pdf_to_markdown", return_value="curto"):
        result = _ensure_parsed(raw, parsed, "doc")

    assert result is False
    assert not parsed.exists()


def test_ensure_parsed_returns_false_on_exception(tmp_path):
    raw = tmp_path / "doc.pdf"
    raw.write_bytes(b"fake")
    parsed = tmp_path / "doc.md"

    with patch("pipeline.agents.corpus_scanner._pdf_to_markdown", side_effect=Exception("boom")):
        result = _ensure_parsed(raw, parsed, "doc")

    assert result is False
