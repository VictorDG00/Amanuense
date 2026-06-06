from __future__ import annotations
import hashlib
from datetime import date, datetime
from pathlib import Path
from .base import BaseAgent, console
from ..corpus_registry import load_registry, save_registry, detect_metadata


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


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
