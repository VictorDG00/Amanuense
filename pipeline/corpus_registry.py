from __future__ import annotations
import json
import re
from datetime import date
from pathlib import Path

_REGISTRY_FILE = "registry.json"


def registry_path(corpus_dir: Path) -> Path:
    return corpus_dir / _REGISTRY_FILE


def load_registry(corpus_dir: Path) -> dict[str, dict]:
    p = registry_path(corpus_dir)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_registry(corpus_dir: Path, registry: dict[str, dict]) -> None:
    corpus_dir.mkdir(parents=True, exist_ok=True)
    registry_path(corpus_dir).write_text(
        json.dumps(registry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def detect_metadata(stem: str) -> dict:
    """Auto-detect document metadata from a filename stem."""
    s = stem.lower().replace("_", "-")

    m = re.match(r"resolucao-([a-z]+)-(\d+)-(\d{4})", s)
    if m:
        return _meta("resolucao", m.group(1).upper(), m.group(2), int(m.group(3)), stem)

    m = re.match(r"circular-([a-z]+)-(\d+)-(\d{4})", s)
    if m:
        return _meta("circular", m.group(1).upper(), m.group(2), int(m.group(3)), stem)

    m = re.match(r"instrucao-normativa-([a-z]+)-(\d+)-(\d{4})", s)
    if m:
        return _meta("instrucao_normativa", m.group(1).upper(), m.group(2), int(m.group(3)), stem)

    m = re.match(r"lei-complementar-(\d+)-(\d{4})", s)
    if m:
        return _meta("lei_complementar", "Federal", m.group(1), int(m.group(2)), stem)

    m = re.match(r"lei-(\d+)-(\d{4})", s)
    if m:
        return _meta("lei_ordinaria", "Federal", m.group(1), int(m.group(2)), stem)

    if s.startswith("manual-"):
        return _meta("manual", "BCB", None, date.today().year, stem)

    return _meta("resolucao", "BCB", None, date.today().year, stem)


def _meta(doc_type: str, authority: str, number: str | None, year: int, stem: str) -> dict:
    return {
        "authority": authority,
        "type": doc_type,
        "number": number,
        "year": year,
        "dataPublicacao": f"{year}-01-01",
        "dataVigor": f"{year}-01-01",
        "vigencyStatus": "vigente",
        "description": stem.replace("-", " ").title(),
    }
