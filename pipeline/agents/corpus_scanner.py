from __future__ import annotations
import hashlib
from datetime import date, datetime
from pathlib import Path
from .base import BaseAgent, console
from ..schemas import VigencyStatus

MVP_CORPUS: dict[str, dict] = {
    "resolucao-bcb-001-2020": {
        "authority": "BCB",
        "type": "resolucao",
        "number": "1",
        "year": 2020,
        "dataPublicacao": "2020-11-12",
        "dataVigor": "2020-11-16",
        "vigencyStatus": VigencyStatus.VIGENTE,
        "description": "Regulamento do arranjo de pagamentos Pix",
    },
    "circular-bcb-3952-2019": {
        "authority": "BCB",
        "type": "circular",
        "number": "3952",
        "year": 2019,
        "dataPublicacao": "2019-12-12",
        "dataVigor": "2020-11-16",
        "vigencyStatus": VigencyStatus.VIGENTE,
        "description": "Regulamenta o arranjo de pagamentos denominado Pix",
    },
    "circular-bcb-4027-2020": {
        "authority": "BCB",
        "type": "circular",
        "number": "4027",
        "year": 2020,
        "dataPublicacao": "2020-11-12",
        "dataVigor": "2021-02-01",
        "vigencyStatus": VigencyStatus.VIGENTE,
        "description": "Altera o Regulamento Pix — inserção do ITP como categoria autônoma",
    },
    "circular-bcb-4080-2021": {
        "authority": "BCB",
        "type": "circular",
        "number": "4080",
        "year": 2021,
        "dataPublicacao": "2021-03-24",
        "dataVigor": "2021-03-24",
        "vigencyStatus": VigencyStatus.VIGENTE,
        "description": "Dispõe sobre o Pix — requisitos e procedimentos complementares",
    },
    "manual-requisitos-tecnicos-pix": {
        "authority": "BCB",
        "type": "manual",
        "number": None,
        "year": 2020,
        "dataPublicacao": "2020-11-16",
        "dataVigor": "2020-11-16",
        "vigencyStatus": VigencyStatus.VIGENTE,
        "description": "Manual de Requisitos Técnicos e Operacionais do Pix",
    },
    "manual-seguranca-pix": {
        "authority": "BCB",
        "type": "manual",
        "number": None,
        "year": 2020,
        "dataPublicacao": "2020-11-16",
        "dataVigor": "2020-11-16",
        "vigencyStatus": VigencyStatus.VIGENTE,
        "description": "Manual de Segurança do Pix",
    },
}


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _detect_document_id(path: Path) -> str | None:
    stem = path.stem.lower().replace(" ", "-").replace("_", "-")
    for doc_id in MVP_CORPUS:
        if doc_id in stem or stem in doc_id:
            return doc_id
    return None


class CorpusScannerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("corpus-scanner")

    def run(self, intermediate_dir: Path, corpus_dir: Path) -> None:
        raw_dir = corpus_dir / "raw"
        parsed_dir = corpus_dir / "parsed"
        parsed_dir.mkdir(parents=True, exist_ok=True)

        documents = []
        hashes: dict[str, str] = {}

        all_files = sorted(raw_dir.glob("*.pdf")) + sorted(raw_dir.glob("*.md"))

        for file_path in all_files:
            doc_id = _detect_document_id(file_path)
            if doc_id is None:
                console.print(f"[yellow]? unknown document:[/yellow] {file_path.name}")
                continue

            meta = MVP_CORPUS[doc_id]
            file_hash = _file_hash(file_path)
            hashes[str(file_path.relative_to(corpus_dir))] = file_hash

            parsed_path = parsed_dir / f"{doc_id}.md"

            record = {
                "documentId": doc_id,
                "filePath": str(file_path.relative_to(corpus_dir.parent)),
                "parsedPath": str(parsed_path.relative_to(corpus_dir.parent)),
                "fileHash": file_hash,
                "authority": meta["authority"],
                "type": meta["type"],
                "number": meta["number"],
                "year": meta["year"],
                "dataPublicacao": meta["dataPublicacao"],
                "dataVigor": meta["dataVigor"],
                "vigencyStatus": meta["vigencyStatus"].value,
                "description": meta["description"],
                "parsedSuccessfully": parsed_path.exists(),
            }
            documents.append(record)
            console.print(f"[dim]  {doc_id}[/dim]")

        manifest = {
            "runId": intermediate_dir.name,
            "generatedAt": datetime.now().isoformat(),
            "ultimaVerificacao": date.today().isoformat(),
            "documents": documents,
        }

        self._save_json(intermediate_dir / "scan_manifest.json", manifest)
        self._save_json(intermediate_dir / "corpus_hashes.json", hashes)
