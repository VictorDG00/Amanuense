from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from .base import BaseAgent, load_prompt, console
from ..parsers.structure_parser import parse_document
from ..schemas import (
    GraphNode, NodeType, NormativeLayer, NormaMeta, VigenciaMeta, VigencyStatus,
    LAYER_LEVELS,
)
from ..utils.id_factory import norma_id, artigo_id, inciso_id, paragrafo_id
from ..utils.llm_helpers import parse_json_response

_LAYER_FROM_TYPE: dict[str, NormativeLayer] = {
    "resolucao": NormativeLayer.RESOLUCAO,
    "circular": NormativeLayer.CIRCULAR,
    "instrucao_normativa": NormativeLayer.INSTRUCAO_NORMATIVA,
    "lei_complementar": NormativeLayer.LEI_COMPLEMENTAR,
    "lei_ordinaria": NormativeLayer.LEI_ORDINARIA,
    "manual": NormativeLayer.MANUAL,
    "cf": NormativeLayer.CF,
}


class NormAnalyzerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("norm-analyzer")
        self._prompt = load_prompt("norm-analyzer")

    def run(self, intermediate_dir: Path, corpus_dir: Path) -> None:
        manifest_path = intermediate_dir / "corpus_scanner.json"
        if not manifest_path.exists():
            manifest_path = intermediate_dir / "scan_manifest.json"
        if not manifest_path.exists():
            console.print("[red]ERROR:[/red] scan_manifest.json not found — run corpus-scanner first")
            return

        manifest = self._load_json(manifest_path)
        documents = manifest.get("documents", [])

        all_nodes: list[dict] = []
        corpus_texts: dict[str, dict] = {}
        by_document: dict[str, dict] = {}

        for doc_meta in documents:
            doc_id = doc_meta["documentId"]
            parsed_path = Path(corpus_dir.parent) / doc_meta["parsedPath"]

            if not parsed_path.exists():
                console.print(f"[yellow]⚠[/yellow]  {doc_id}: parsed file missing, skipping")
                continue

            console.print(f"[dim]  analyzing {doc_id}…[/dim]")
            markdown_text = parsed_path.read_text(encoding="utf-8")
            parsed_doc = parse_document(doc_id, markdown_text)

            layer = _LAYER_FROM_TYPE.get(doc_meta.get("type", "").lower(), NormativeLayer.RESOLUCAO)
            vigencia_inicio = date.fromisoformat(doc_meta.get("dataVigor", doc_meta.get("dataPublicacao", "2020-01-01")))
            verificacao = date.today()

            norma_node = GraphNode(
                id=norma_id(doc_id),
                type=NodeType.NORMA,
                name=doc_meta.get("description", doc_id),
                summary=doc_meta.get("description", ""),
                tags=[doc_meta.get("type", ""), doc_meta.get("authority", "").lower()],
                normativeLayer=layer,
                sourceDocument=doc_id,
                vigenciaMeta=VigenciaMeta(
                    dataInicio=vigencia_inicio,
                    status=VigencyStatus(doc_meta.get("vigencyStatus", "vigente")),
                    ultimaVerificacao=verificacao,
                ),
                normaMeta=NormaMeta(
                    autoridade=doc_meta.get("authority", ""),
                    tipoNorma=doc_meta.get("type", ""),
                    numero=str(doc_meta.get("number", "")) if doc_meta.get("number") else None,
                    ano=doc_meta.get("year"),
                ),
            )

            doc_nodes = [norma_node.model_dump(mode="json")]
            art_texts: dict[str, str] = {}

            # Collect article texts for corpus-texts
            for artigo in parsed_doc.artigos:
                art_node_id = artigo_id(doc_id, artigo.number)
                art_texts[art_node_id] = artigo.text

            # LLM summaries in batches
            summaries: dict[str, dict] = {}
            art_list = parsed_doc.artigos
            batch_size = 10
            for i in range(0, len(art_list), batch_size):
                batch = art_list[i : i + batch_size]
                items_text = "\n\n".join(
                    f"[{j + 1}] {a.header} — {a.text[:600]}"
                    for j, a in enumerate(batch)
                )
                try:
                    raw = self.client.call(system=self._prompt, user=items_text)
                    parsed = parse_json_response(raw, self.client, f"{doc_id} batch {i}")
                    for entry in parsed:
                        idx = int(entry["artigo"]) - 1
                        if 0 <= idx < len(batch):
                            art = batch[idx]
                            summaries[art.number] = {
                                "summary": entry.get("summary", ""),
                                "tags": entry.get("tags", []),
                            }
                except Exception as e:
                    console.print(f"[yellow]⚠[/yellow]  LLM batch {i} failed: {e}")

            # Build artigo nodes
            for artigo in parsed_doc.artigos:
                art_node_id = artigo_id(doc_id, artigo.number)
                llm = summaries.get(artigo.number, {})
                art_node = GraphNode(
                    id=art_node_id,
                    type=NodeType.ARTIGO,
                    name=f"{artigo.header} — {doc_id}",
                    summary=llm.get("summary", artigo.text[:200]),
                    tags=llm.get("tags", []),
                    normativeLayer=layer,
                    sourceDocument=doc_id,
                    articleNumber=artigo.number,
                    vigenciaMeta=VigenciaMeta(
                        dataInicio=vigencia_inicio,
                        status=VigencyStatus.VIGENTE,
                        ultimaVerificacao=verificacao,
                    ),
                    normaMeta=NormaMeta(
                        autoridade=doc_meta.get("authority", ""),
                        tipoNorma=doc_meta.get("type", ""),
                        numero=str(doc_meta.get("number", "")) if doc_meta.get("number") else None,
                        ano=doc_meta.get("year"),
                        dispositivo=artigo.header,
                    ),
                    review_required=artigo.number not in summaries,
                )
                doc_nodes.append(art_node.model_dump(mode="json"))

                # corpus text entry
                corpus_texts[art_node_id] = {
                    "textoCompleto": artigo.text,
                    "caput": artigo.text.split("\n")[0] if artigo.text else "",
                    "incisos": {inc.numeral: inc.text for inc in artigo.incisos},
                    "paragrafos": {par.number: par.text for par in artigo.paragrafos},
                    "alineas": {al.letter: al.text for al in artigo.alineas},
                    "versoes": {},
                }

                # inciso nodes
                for inc in artigo.incisos:
                    inc_node_id = inciso_id(doc_id, artigo.number, inc.numeral)
                    inc_node = GraphNode(
                        id=inc_node_id,
                        type=NodeType.INCISO,
                        name=f"{artigo.header}, inciso {inc.numeral} — {doc_id}",
                        summary=inc.text[:200],
                        tags=[],
                        normativeLayer=layer,
                        sourceDocument=doc_id,
                        articleNumber=artigo.number,
                        vigenciaMeta=VigenciaMeta(
                            dataInicio=vigencia_inicio,
                            status=VigencyStatus.VIGENTE,
                            ultimaVerificacao=verificacao,
                        ),
                    )
                    doc_nodes.append(inc_node.model_dump(mode="json"))

            all_nodes.extend(doc_nodes)
            by_document[doc_id] = {
                "nodes": doc_nodes,
                "artCount": len(parsed_doc.artigos),
            }
            console.print(f"[green]✓[/green] {doc_id}: {len(parsed_doc.artigos)} artigos")

        output = {
            "generatedAt": datetime.now().isoformat(),
            "byDocument": by_document,
            "allNodeIds": [n["id"] for n in all_nodes],
            "totalNodes": len(all_nodes),
        }
        self._save_json(intermediate_dir / "norm_analyzer.json", output)

        # save corpus texts separately for graph-builder
        corpus_texts_output = {
            "generatedAt": datetime.now().isoformat(),
            "texts": corpus_texts,
        }
        self._save_json(intermediate_dir / "corpus_texts_builder.json", corpus_texts_output)
