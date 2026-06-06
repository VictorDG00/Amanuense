from __future__ import annotations
import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from .base import BaseAgent, console
from ..corpus_registry import load_registry, save_registry, detect_metadata


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _clean_text(text: str) -> str:
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    return text.strip()


def _pdf_to_markdown(pdf_path: Path) -> str:
    try:
        import pdfplumber
        pages: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
                pages.append(text)
        result = _clean_text("\n\n".join(pages))
        if len(result.strip()) >= 100:
            return result
    except Exception:
        pass

    import fitz
    doc = fitz.open(str(pdf_path))
    pages = [page.get_text("text") for page in doc]
    doc.close()
    return _clean_text("\n\n".join(pages))


def _ensure_parsed(raw_file: Path, parsed_path: Path, doc_id: str) -> bool:
    if parsed_path.exists():
        return True
    try:
        text = _pdf_to_markdown(raw_file)
        if len(text.strip()) < 50:
            console.print(f"[yellow]⚠[/yellow]  {doc_id}: texto extraído muito curto, PDF pode ser imagem")
            return False
        parsed_path.parent.mkdir(parents=True, exist_ok=True)
        parsed_path.write_text(text, encoding="utf-8")
        console.print(f"[green]✓[/green]  {doc_id}: PDF convertido ({len(text)} chars)")
        return True
    except Exception as e:
        console.print(f"[red]✗[/red]  {doc_id}: falha ao converter PDF — {e}")
        return False


class CorpusScannerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("corpus-scanner")

    def run(self, intermediate_dir: Path, corpus_dir: Path) -> None:
        registry = load_registry(corpus_dir)
        raw_dir = corpus_dir / "raw"
        parsed_dir = corpus_dir / "parsed"
        parsed_dir.mkdir(parents=True, exist_ok=True)

        # Auto-register any PDFs that aren't in the registry yet
        if raw_dir.exists():
            changed = False
            for pdf in sorted(raw_dir.glob("*.pdf")):
                doc_id = pdf.stem.lower().replace("_", "-")
                if doc_id not in registry:
                    registry[doc_id] = detect_metadata(pdf.stem)
                    console.print(f"[dim]  auto-registered: {doc_id}[/dim]")
                    changed = True
            if changed:
                save_registry(corpus_dir, registry)

        if not registry:
            console.print("[yellow]⚠[/yellow]  corpus registry is empty — upload documents first")

        documents = []
        hashes: dict[str, str] = {}

        for doc_id, meta in registry.items():
            raw_file = raw_dir / f"{doc_id}.pdf"
            if not raw_file.exists():
                raw_file_md = raw_dir / f"{doc_id}.md"
                if not raw_file_md.exists():
                    console.print(f"[yellow]⚠[/yellow]  {doc_id}: file missing in corpus/raw/")
                    continue
                raw_file = raw_file_md

            parsed_path = parsed_dir / f"{doc_id}.md"

            # Auto-convert PDF to Markdown if not done yet
            if raw_file.suffix.lower() == ".pdf":
                _ensure_parsed(raw_file, parsed_path, doc_id)

            file_hash = _file_hash(raw_file)
            hashes[str(raw_file.relative_to(corpus_dir))] = file_hash

            documents.append({
                "documentId": doc_id,
                "filePath": str(raw_file.relative_to(corpus_dir.parent)),
                "parsedPath": str(parsed_path.relative_to(corpus_dir.parent)),
                "fileHash": file_hash,
                "authority": meta.get("authority", "BCB"),
                "type": meta.get("type", "resolucao"),
                "number": meta.get("number"),
                "year": meta.get("year", date.today().year),
                "dataPublicacao": meta.get("dataPublicacao", date.today().isoformat()),
                "dataVigor": meta.get("dataVigor", date.today().isoformat()),
                "vigencyStatus": meta.get("vigencyStatus", "vigente"),
                "description": meta.get("description", doc_id),
                "parsedSuccessfully": parsed_path.exists(),
            })
            console.print(f"[dim]  {doc_id}[/dim]")

        manifest = {
            "runId": intermediate_dir.name,
            "generatedAt": datetime.now().isoformat(),
            "ultimaVerificacao": date.today().isoformat(),
            "documents": documents,
        }

        self._save_json(intermediate_dir / "scan_manifest.json", manifest)
        self._save_json(intermediate_dir / "corpus_hashes.json", hashes)
