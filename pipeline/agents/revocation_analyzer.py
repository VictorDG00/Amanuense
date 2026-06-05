from __future__ import annotations
import re
from datetime import date, datetime
from pathlib import Path
from .base import BaseAgent, console
from ..parsers.bcb_patterns import (
    REVOGA_EXPRESSAMENTE_PATTERNS,
    REVOGA_PARCIALMENTE_PATTERNS,
    SUSPENDE_PATTERNS,
    EXCECAO_RE,
    ANAFORA_RE,
    CROSS_REF_RE,
)
from ..schemas import EdgeType, VigencyStatus, EDGE_DEFAULT_WEIGHTS
from ..utils.id_factory import norma_id, artigo_id, versao_id, edge_id


def _resolve_target(doc_lookup: dict[str, str], ref_doc: str | None, art_num: str | None, fallback_doc: str) -> str | None:
    if not art_num:
        return None
    target_doc = doc_lookup.get(ref_doc, fallback_doc) if ref_doc else fallback_doc
    return artigo_id(target_doc, art_num)


class RevocationAnalyzerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("revocation-analyzer")

    def run(self, intermediate_dir: Path, corpus_dir: Path) -> None:
        manifest_path = intermediate_dir / "corpus_scanner.json"
        if not manifest_path.exists():
            manifest_path = intermediate_dir / "scan_manifest.json"
        norm_path = intermediate_dir / "norm_analyzer.json"

        if not manifest_path.exists() or not norm_path.exists():
            console.print("[red]ERROR:[/red] Prerequisites missing")
            return

        manifest = self._load_json(manifest_path)
        norm_data = self._load_json(norm_path)
        documents = manifest.get("documents", [])

        # build lookup from number/year → doc_id
        doc_lookup: dict[str, str] = {}
        for doc in documents:
            doc_id = doc["documentId"]
            doc_lookup[doc_id] = doc_id
            num = str(doc.get("number", "") or "")
            year = str(doc.get("year", "") or "")
            if num and year:
                doc_lookup[f"{num}/{year}"] = doc_id
                doc_lookup[f"{num}.{year}"] = doc_id
            if num:
                doc_lookup[num] = doc_id

        # all known article node IDs
        known_art_ids: set[str] = set()
        for doc_id, doc_info in norm_data.get("byDocument", {}).items():
            for n in doc_info.get("nodes", []):
                if n.get("type") in ("artigo", "inciso", "norma"):
                    known_art_ids.add(n["id"])

        edges: list[dict] = []
        vigency_updates: list[dict] = []
        diff_log_entries: list[dict] = []
        version_nodes: list[dict] = []

        for doc in documents:
            doc_id = doc["documentId"]
            parsed_path = Path(corpus_dir.parent) / doc.get("parsedPath", "")
            if not parsed_path.exists():
                continue

            text = parsed_path.read_text(encoding="utf-8")
            dataVigor = doc.get("dataVigor") or doc.get("dataPublicacao") or date.today().isoformat()

            # Scan sentences for revocation patterns
            sentences = re.split(r'(?<=[.;])\s+', text)
            for sentence in sentences:
                is_express = any(p.search(sentence) for p in REVOGA_EXPRESSAMENTE_PATTERNS)
                is_partial = not is_express and any(p.search(sentence) for p in REVOGA_PARCIALMENTE_PATTERNS)
                is_suspend = any(p.search(sentence) for p in SUSPENDE_PATTERNS)

                if not (is_express or is_partial or is_suspend):
                    continue

                has_exception = bool(EXCECAO_RE.search(sentence))
                has_anaphora = bool(ANAFORA_RE.search(sentence))
                needs_review = has_exception or has_anaphora

                # Determine edge type
                if is_express:
                    etype = EdgeType.REVOGA_EXPRESSAMENTE
                    new_status = VigencyStatus.REVOGADO
                    change_type = "revoke"
                elif is_suspend:
                    etype = EdgeType.SUSPENDE
                    new_status = VigencyStatus.SUSPENSO
                    change_type = "suspend"
                else:
                    etype = EdgeType.ALTERA
                    new_status = VigencyStatus.ALTERADO
                    change_type = "alter"

                # Extract referenced articles
                for ref_match in CROSS_REF_RE.finditer(sentence):
                    art_num = ref_match.group(1)
                    ref_doc_num = ref_match.group(2)
                    if not art_num:
                        continue

                    target_doc_id = doc_lookup.get(ref_doc_num, doc_id) if ref_doc_num else doc_id
                    target_art_id = artigo_id(target_doc_id, art_num)

                    # source: find enclosing article
                    art_before = text[: text.find(sentence)].rfind("Art.")
                    src_art_match = re.search(r"Art\.\s*(\d+(?:-[A-Z])?)", text[max(0, art_before) : art_before + 30])
                    src_art_num = src_art_match.group(1) if src_art_match else "disposicoes-finais"
                    src_art_id = artigo_id(doc_id, src_art_num)

                    eid = edge_id(src_art_id, etype.value, target_art_id)
                    is_external = target_art_id not in known_art_ids

                    edges.append({
                        "id": eid,
                        "source": src_art_id,
                        "target": target_art_id,
                        "type": etype.value,
                        "weight": EDGE_DEFAULT_WEIGHTS[etype],
                        "direction": "forward",
                        "implicit": False,
                        "confidence": 1.0,
                        "textEvidence": sentence[:300],
                        "dataEfeito": dataVigor,
                        "review_required": needs_review or is_external,
                        "deprecated": False,
                        "stale": False,
                    })

                    if not is_external:
                        vigency_updates.append({
                            "nodeId": target_art_id,
                            "newStatus": new_status.value,
                            "edgeId": eid,
                            "dataEfeito": dataVigor,
                        })

                    diff_log_entries.append({
                        "data": dataVigor,
                        "normaOrigem": norma_id(doc_id),
                        "tipo": change_type,
                        "dispositivo": target_art_id,
                        "descricao": sentence[:200],
                        "impacto": "alto" if etype == EdgeType.REVOGA_EXPRESSAMENTE else "medio",
                        "nosAfetados": [target_art_id, src_art_id],
                    })

                    # For partial revocation: create version node
                    if etype == EdgeType.ALTERA and not is_external:
                        ver_id = versao_id(target_art_id, 1)
                        version_nodes.append({
                            "id": ver_id,
                            "sourceNodeId": target_art_id,
                            "normaAlteracao": norma_id(doc_id),
                            "dataAlteracao": dataVigor,
                            "sentence": sentence[:300],
                        })
                        # SUCEDE edge: new version succeeds old
                        sucede_eid = edge_id(target_art_id, EdgeType.SUCEDE.value, ver_id)
                        edges.append({
                            "id": sucede_eid,
                            "source": target_art_id,
                            "target": ver_id,
                            "type": EdgeType.SUCEDE.value,
                            "weight": EDGE_DEFAULT_WEIGHTS[EdgeType.SUCEDE],
                            "direction": "forward",
                            "implicit": False,
                            "review_required": False,
                            "description": f"Versão histórica criada por {doc_id}",
                        })

        output = {
            "generatedAt": datetime.now().isoformat(),
            "edges": edges,
            "vigencyUpdates": vigency_updates,
            "diffLogEntries": diff_log_entries,
            "versionNodes": version_nodes,
        }
        self._save_json(intermediate_dir / "revocation_analyzer.json", output)
        console.print(
            f"[green]✓[/green] revocation-analyzer: {len(edges)} edges, "
            f"{len(vigency_updates)} vigency updates, {len(diff_log_entries)} diff entries"
        )
