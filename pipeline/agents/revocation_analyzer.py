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
from ..schemas import EdgeType, EDGE_DEFAULT_WEIGHTS
from ..utils.id_factory import canon_artigo, disp_node_id, edge_id

# tipo de relação na base estruturada por tipo de aresta detectada
_RELACAO_POR_EDGE = {
    EdgeType.REVOGA_EXPRESSAMENTE: "revoga",
    EdgeType.ALTERA: "altera",
    EdgeType.SUSPENDE: "suspende",
}


class RevocationAnalyzerAgent(BaseAgent):
    """Detecta revogações/alterações/suspensões por regex e as registra.

    As arestas continuam alimentando o grafo; quando a base estruturada está
    habilitada, as detecções também são gravadas nela: revogação expressa via
    fn_registrar_revogacao (o motor versiona e propaga em cascata) e
    alteração/suspensão como relacao_normativa. A alteração de texto NUNCA é
    aplicada aqui — sem a nova redação extraída da fonte não há nova versão
    (anti-alucinação); o evento fica em relacao_normativa e na fila de revisão.
    """

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

        # all known normative node IDs
        known_art_ids: set[str] = set()
        for doc_id, doc_info in norm_data.get("byDocument", {}).items():
            for n in doc_info.get("nodes", []):
                if n.get("type") in ("artigo", "inciso", "norma"):
                    known_art_ids.add(n["id"])

        edges: list[dict] = []
        diff_log_entries: list[dict] = []
        detections: list[dict] = []  # p/ gravação na base estruturada

        for doc in documents:
            doc_id = doc["documentId"]
            parsed_path = Path(corpus_dir.parent) / doc.get("parsedPath", "")
            if not parsed_path.exists():
                continue

            text = parsed_path.read_text(encoding="utf-8")
            dataVigor = doc.get("dataVigor") or doc.get("dataPublicacao") or date.today().isoformat()

            # Scan sentences for revocation patterns. O split exige letra
            # maiúscula/§ à frente para não quebrar em "art. 4", "nº 42." etc.
            sentences = re.split(r'(?<=[.;])\s+(?=[A-ZÀ-Ú§])', text)
            for sentence in sentences:
                is_express = any(p.search(sentence) for p in REVOGA_EXPRESSAMENTE_PATTERNS)
                is_partial = not is_express and any(p.search(sentence) for p in REVOGA_PARCIALMENTE_PATTERNS)
                is_suspend = any(p.search(sentence) for p in SUSPENDE_PATTERNS)

                if not (is_express or is_partial or is_suspend):
                    continue

                has_exception = bool(EXCECAO_RE.search(sentence))
                has_anaphora = bool(ANAFORA_RE.search(sentence))
                needs_review = has_exception or has_anaphora

                if is_express:
                    etype = EdgeType.REVOGA_EXPRESSAMENTE
                    change_type = "revoke"
                elif is_suspend:
                    etype = EdgeType.SUSPENDE
                    change_type = "suspend"
                else:
                    etype = EdgeType.ALTERA
                    change_type = "alter"

                # Extract referenced articles — sem o cabeçalho do próprio
                # artigo ("Art. 2º Fica revogado..."), que não é alvo
                scan_sentence = re.sub(
                    r"^Art\.\s*\d+(?:-[A-Z])?\s*[º°]?\.?\s*", "", sentence
                )
                for ref_match in CROSS_REF_RE.finditer(scan_sentence):
                    art_num = ref_match.group(1)
                    ref_doc_num = ref_match.group(2)
                    if not art_num:
                        continue

                    target_doc_id = doc_lookup.get(ref_doc_num, doc_id) if ref_doc_num else doc_id
                    try:
                        target_canon = canon_artigo(art_num)
                    except ValueError:
                        continue
                    target_art_id = disp_node_id(target_doc_id, target_canon)

                    # source: find enclosing article
                    art_before = text[: text.find(sentence)].rfind("Art.")
                    src_art_match = re.search(r"Art\.\s*(\d+(?:-[A-Z])?)", text[max(0, art_before) : art_before + 30])
                    src_art_num = src_art_match.group(1) if src_art_match else None
                    src_canon = canon_artigo(src_art_num) if src_art_num else None
                    src_art_id = (
                        disp_node_id(doc_id, src_canon) if src_canon
                        else disp_node_id(doc_id, "disposicoesfinais")
                    )

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

                    diff_log_entries.append({
                        "data": dataVigor,
                        "normaOrigem": f"norma:{doc_id}",
                        "tipo": change_type,
                        "dispositivo": target_art_id,
                        "descricao": sentence[:200],
                        "impacto": "alto" if etype == EdgeType.REVOGA_EXPRESSAMENTE else "medio",
                        "nosAfetados": [target_art_id, src_art_id],
                    })

                    if not is_external and not needs_review:
                        detections.append({
                            "etype": etype,
                            "origem_doc": doc_id,
                            "origem_canon": src_canon,
                            "destino_doc": target_doc_id,
                            "destino_canon": target_canon,
                            "data_efeito": dataVigor,
                            "evidencia": sentence[:300],
                        })

        db_stats = self._gravar_na_base(intermediate_dir, detections)

        output = {
            "generatedAt": datetime.now().isoformat(),
            "edges": edges,
            "diffLogEntries": diff_log_entries,
            "dbStats": db_stats,
        }
        self._save_json(intermediate_dir / "revocation_analyzer.json", output)
        console.print(
            f"[green]✓[/green] revocation-analyzer: {len(edges)} edges, "
            f"{len(diff_log_entries)} diff entries, db={db_stats}"
        )

    # ── Gravação na base estruturada ─────────────────────────────────────
    def _gravar_na_base(self, intermediate_dir: Path, detections: list[dict]) -> dict:
        from db.legislacao import legislacao_enabled

        stats = {"revogacoes": 0, "relacoes": 0, "fila": 0, "enabled": legislacao_enabled()}
        if not legislacao_enabled() or not detections:
            return stats

        loader_path = intermediate_dir / "legislation_loader.json"
        if not loader_path.exists():
            console.print("[yellow]⚠[/yellow] legislation_loader.json ausente — gravação pulada")
            return stats
        normas = self._load_json(loader_path).get("normas", {})

        from db.legislacao import get_conn

        detections.sort(key=lambda d: d["data_efeito"])
        with get_conn() as conn:
            for det in detections:
                origem = normas.get(det["origem_doc"], {}).get("norma_id")
                destino = normas.get(det["destino_doc"], {}).get("norma_id")
                if origem is None or destino is None:
                    continue
                disp_row = conn.execute(
                    "SELECT id_dispositivo FROM dispositivo "
                    "WHERE id_norma = %s AND id_canonico = %s",
                    (destino, det["destino_canon"]),
                ).fetchone()
                if disp_row is None:
                    stats["fila"] += 1
                    continue
                disp_id = disp_row[0]
                origem_disp = None
                if det["origem_canon"]:
                    row = conn.execute(
                        "SELECT id_dispositivo FROM dispositivo "
                        "WHERE id_norma = %s AND id_canonico = %s",
                        (origem, det["origem_canon"]),
                    ).fetchone()
                    origem_disp = row[0] if row else None

                if det["etype"] == EdgeType.REVOGA_EXPRESSAMENTE:
                    ja_revogado = conn.execute(
                        "SELECT 1 FROM dispositivo_versao WHERE id_dispositivo = %s "
                        "AND evento = 'revogacao'", (disp_id,),
                    ).fetchone()
                    if ja_revogado:
                        continue
                    try:
                        conn.execute(
                            "SELECT fn_registrar_revogacao(%s,%s,%s,TRUE,%s)",
                            (disp_id, origem, det["data_efeito"], origem_disp),
                        )
                        conn.commit()
                        stats["revogacoes"] += 1
                    except Exception as e:
                        conn.rollback()
                        console.print(f"[yellow]⚠[/yellow] revogação não aplicada: {str(e)[:120]}")
                        stats["fila"] += 1
                else:
                    # ALTERA sem a nova redação / SUSPENDE: só o vínculo — a
                    # versão de texto exige a redação oficial (fila manual)
                    tipo_rel = _RELACAO_POR_EDGE[det["etype"]]
                    dup = conn.execute(
                        "SELECT 1 FROM relacao_normativa WHERE id_norma_origem = %s "
                        "AND id_norma_destino = %s AND id_dispositivo_destino = %s "
                        "AND tipo_relacao = %s AND data_efeito = %s",
                        (origem, destino, disp_id, tipo_rel, det["data_efeito"]),
                    ).fetchone()
                    if dup:
                        continue
                    conn.execute(
                        "INSERT INTO relacao_normativa (id_norma_origem, "
                        "id_dispositivo_origem, tipo_relacao, id_norma_destino, "
                        "id_dispositivo_destino, data_efeito, observacao) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (origem, origem_disp, tipo_rel, destino, disp_id,
                         det["data_efeito"], det["evidencia"]),
                    )
                    conn.commit()
                    stats["relacoes"] += 1
        return stats
