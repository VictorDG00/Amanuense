from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
from .base import BaseAgent, load_prompt, console
from ..parsers.canonical_tree import build_canonical_tree
from ..parsers.history_patterns import build_corpus_index
from ..schemas import (
    GraphNode, NodeType, NormativeLayer, NormaMeta, VigenciaMeta, VigencyStatus,
)
from ..schemas.legislacao import DispositivoCanonico, NormaCanonica, texto_vigente
from ..utils.id_factory import norma_id, disp_node_id
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

_NODE_TYPE_POR_TIPO: dict[str, NodeType] = {
    "artigo": NodeType.ARTIGO,
    "paragrafo": NodeType.PARAGRAFO,
    "inciso": NodeType.INCISO,
    "alinea": NodeType.ALINEA,
    "item": NodeType.ITEM,
    "subitem": NodeType.SUBITEM,
}


def _texto_completo(disp: DispositivoCanonico) -> str:
    """Texto do dispositivo + subárvore (rotulados), para sumário e corpus-texts."""
    partes: list[str] = []

    def _emit(d: DispositivoCanonico) -> None:
        texto = texto_vigente(d)
        if texto:
            partes.append(f"{d.rotulo} {texto}" if d.tipo != "artigo" else texto)
        for f in d.filhos:
            _emit(f)

    _emit(disp)
    return "\n".join(partes)


class NormAnalyzerAgent(BaseAgent):
    """Gera os nós do grafo a partir da árvore canônica (fonte: legislation-loader).

    A estrutura e os textos vêm da árvore; o LLM contribui apenas com
    summaries e tags dos artigos.
    """

    def __init__(self) -> None:
        super().__init__("norm-analyzer")
        self._prompt = load_prompt("norm-analyzer")

    def _arvore(
        self, intermediate_dir: Path, corpus_dir: Path, doc_meta: dict, corpus_index: dict
    ) -> NormaCanonica | None:
        doc_id = doc_meta["documentId"]
        tree_path = intermediate_dir / "canonical_tree" / f"{doc_id}.json"
        if tree_path.exists():
            return NormaCanonica.model_validate(self._load_json(tree_path))
        # fallback: legislation-loader não rodou — gera a árvore na hora
        parsed_path = Path(corpus_dir.parent) / doc_meta["parsedPath"]
        if not parsed_path.exists():
            return None
        return build_canonical_tree(
            doc_id, parsed_path.read_text(encoding="utf-8"), doc_meta, corpus_index
        )

    def run(self, intermediate_dir: Path, corpus_dir: Path) -> None:
        manifest_path = intermediate_dir / "corpus_scanner.json"
        if not manifest_path.exists():
            manifest_path = intermediate_dir / "scan_manifest.json"
        if not manifest_path.exists():
            console.print("[red]ERROR:[/red] scan_manifest.json not found — run corpus-scanner first")
            return

        manifest = self._load_json(manifest_path)
        documents = manifest.get("documents", [])
        corpus_index = build_corpus_index(documents)

        # Load previous output for incremental processing
        output_path = intermediate_dir / "norm_analyzer.json"
        corpus_texts_path = intermediate_dir / "corpus_texts_builder.json"
        existing_output = self._load_json(output_path) if output_path.exists() else None
        existing_texts = (
            self._load_json(corpus_texts_path)["texts"]
            if corpus_texts_path.exists()
            else {}
        )

        # processed_doc_ids: {doc_id -> fileHash} from previous run
        processed_hashes: dict[str, str] = {}
        by_document: dict[str, dict] = {}
        corpus_texts: dict[str, dict] = dict(existing_texts)
        if existing_output:
            processed_hashes = existing_output.get("processedDocIds", {})
            by_document = existing_output.get("byDocument", {})

        # Current file hashes from manifest
        current_hashes: dict[str, str] = {
            d["documentId"]: d.get("fileHash", "") for d in documents
        }

        for doc_meta in documents:
            doc_id = doc_meta["documentId"]
            current_hash = current_hashes.get(doc_id, "")

            # Skip documents already processed with the same file hash
            if processed_hashes.get(doc_id) == current_hash and current_hash:
                console.print(f"[dim]  {doc_id}: unchanged, reusing cached result[/dim]")
                continue

            arvore = self._arvore(intermediate_dir, corpus_dir, doc_meta, corpus_index)
            if arvore is None:
                console.print(f"[yellow]⚠[/yellow]  {doc_id}: parsed file missing, skipping")
                continue

            console.print(f"[dim]  analyzing {doc_id}…[/dim]")
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
            artigos = arvore.dispositivos

            # LLM summaries in batches (somente artigos)
            summaries: dict[str, dict] = {}
            batch_size = 10
            for i in range(0, len(artigos), batch_size):
                batch = artigos[i : i + batch_size]
                items_text = "\n\n".join(
                    f"[{j + 1}] {a.rotulo} — {_texto_completo(a)[:600]}"
                    for j, a in enumerate(batch)
                )
                try:
                    raw = self.client.call(system=self._prompt, user=items_text)
                    parsed = parse_json_response(raw, self.client, f"{doc_id} batch {i}")
                    for entry in parsed:
                        idx = int(entry["artigo"]) - 1
                        if 0 <= idx < len(batch):
                            summaries[batch[idx].id_canonico] = {
                                "summary": entry.get("summary", ""),
                                "tags": entry.get("tags", []),
                            }
                except Exception as e:
                    console.print(f"[yellow]⚠[/yellow]  LLM batch {i} failed: {e}")

            # Nós de dispositivos (artigo + subárvore inteira)
            for artigo in artigos:
                art_node_id = disp_node_id(doc_id, artigo.id_canonico)
                texto_art = _texto_completo(artigo)
                llm = summaries.get(artigo.id_canonico, {})
                art_node = GraphNode(
                    id=art_node_id,
                    type=NodeType.ARTIGO,
                    name=f"{artigo.rotulo} — {doc_id}",
                    summary=llm.get("summary", texto_art[:200]),
                    tags=llm.get("tags", []),
                    normativeLayer=layer,
                    sourceDocument=doc_id,
                    articleNumber=artigo.numero,
                    idCanonico=artigo.id_canonico,
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
                        dispositivo=artigo.rotulo,
                    ),
                    review_required=artigo.review_required
                    or artigo.id_canonico not in summaries,
                )
                doc_nodes.append(art_node.model_dump(mode="json"))

                # corpus text entry (estrutura da árvore canônica)
                corpus_texts[art_node_id] = {
                    "textoCompleto": texto_art,
                    "caput": texto_vigente(artigo) or "",
                    "incisos": {
                        f.numero: texto_vigente(f) or ""
                        for f in artigo.filhos if f.tipo == "inciso"
                    },
                    "paragrafos": {
                        f.numero: texto_vigente(f) or ""
                        for f in artigo.filhos if f.tipo == "paragrafo"
                    },
                    "alineas": {
                        neto.numero: texto_vigente(neto) or ""
                        for f in artigo.filhos
                        for neto in f.filhos if neto.tipo == "alinea"
                    },
                    "versoes": {},
                }

                # nós dos dispositivos filhos (parágrafo/inciso/alínea/item/subitem)
                pendentes = list(artigo.filhos)
                while pendentes:
                    disp = pendentes.pop(0)
                    pendentes.extend(disp.filhos)
                    texto_disp = texto_vigente(disp) or ""
                    child_node = GraphNode(
                        id=disp_node_id(doc_id, disp.id_canonico),
                        type=_NODE_TYPE_POR_TIPO[disp.tipo],
                        name=f"{artigo.rotulo}, {disp.rotulo} — {doc_id}",
                        summary=texto_disp[:200],
                        tags=[],
                        normativeLayer=layer,
                        sourceDocument=doc_id,
                        articleNumber=artigo.numero,
                        idCanonico=disp.id_canonico,
                        vigenciaMeta=VigenciaMeta(
                            dataInicio=vigencia_inicio,
                            status=VigencyStatus.VIGENTE,
                            ultimaVerificacao=verificacao,
                        ),
                        review_required=disp.review_required,
                    )
                    doc_nodes.append(child_node.model_dump(mode="json"))

            by_document[doc_id] = {
                "nodes": doc_nodes,
                "artCount": len(artigos),
            }
            # Update processed hash for this document
            processed_hashes[doc_id] = current_hash
            console.print(f"[green]✓[/green] {doc_id}: {len(artigos)} artigos")

        # Reconstruct all_nodes from merged by_document (includes previously cached docs)
        all_nodes = [n for doc_info in by_document.values() for n in doc_info.get("nodes", [])]

        output = {
            "generatedAt": datetime.now().isoformat(),
            "byDocument": by_document,
            "allNodeIds": [n["id"] for n in all_nodes],
            "totalNodes": len(all_nodes),
            "processedDocIds": processed_hashes,
        }
        self._save_json(intermediate_dir / "norm_analyzer.json", output)

        # save corpus texts separately for graph-builder
        corpus_texts_output = {
            "generatedAt": datetime.now().isoformat(),
            "texts": corpus_texts,
        }
        self._save_json(intermediate_dir / "corpus_texts_builder.json", corpus_texts_output)
