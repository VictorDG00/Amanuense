#!/usr/bin/env python3
"""
Convert PDF files in corpus/raw/ to Markdown in corpus/parsed/.
Uses pdfplumber for text extraction with fallback to PyMuPDF.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import re
from rich.console import Console

console = Console()


def _clean(text: str) -> str:
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    text = text.strip()
    return text


def pdf_to_markdown_pdfplumber(pdf_path: Path) -> str:
    import pdfplumber
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            pages.append(text)
    return _clean("\n\n".join(pages))


def pdf_to_markdown_pymupdf(pdf_path: Path) -> str:
    import fitz
    doc = fitz.open(str(pdf_path))
    pages: list[str] = []
    for page in doc:
        pages.append(page.get_text("text"))
    doc.close()
    return _clean("\n\n".join(pages))


def convert(pdf_path: Path, out_path: Path) -> bool:
    try:
        text = pdf_to_markdown_pdfplumber(pdf_path)
    except Exception:
        try:
            text = pdf_to_markdown_pymupdf(pdf_path)
        except Exception as e:
            console.print(f"[red]FAILED[/red] {pdf_path.name}: {e}")
            return False

    if len(text.strip()) < 100:
        console.print(f"[yellow]⚠[/yellow]  {pdf_path.name}: extracted text too short ({len(text)} chars)")
        return False

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    console.print(f"[green]✓[/green] {pdf_path.name} → {out_path.name} ({len(text)} chars)")
    return True


def main() -> None:
    raw_dir = ROOT / "corpus" / "raw"
    parsed_dir = ROOT / "corpus" / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(raw_dir.glob("*.pdf"))
    if not pdfs:
        console.print(f"[yellow]No PDF files found in {raw_dir}[/yellow]")
        return

    ok = failed = skipped = 0
    for pdf_path in pdfs:
        out_path = parsed_dir / (pdf_path.stem + ".md")
        if out_path.exists():
            console.print(f"[dim]  skipping {pdf_path.name} (already parsed)[/dim]")
            skipped += 1
            continue
        if convert(pdf_path, out_path):
            ok += 1
        else:
            failed += 1

    console.print(f"\n[bold]Done:[/bold] {ok} converted, {failed} failed, {skipped} skipped")


if __name__ == "__main__":
    main()
