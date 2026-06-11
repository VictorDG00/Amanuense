from __future__ import annotations
from datetime import datetime
from pathlib import Path
from .base import BaseAgent, load_prompt, console
from ..schemas import EdgeType, EDGE_DEFAULT_WEIGHTS
from ..utils.id_factory import edge_id, doc_id_from_node
from ..utils.llm_helpers import parse_json_response
from ..config import (
    IMPLICIT_CONFIDENCE_THRESHOLD,
    IMPLICIT_CONFIDENCE_AUTO_APPROVE,
    MAX_IMPLICIT_EDGES_PER_ARTICLE,
    IMPLICATION_BATCH_SIZE,
)

_VALID_EDGE_TYPES = {
    EdgeType.OBRIGA, EdgeType.PERMITE, EdgeType.PROIBE, EdgeType.DEFINE,
    EdgeType.CONDICIONA, EdgeType.COMPLEMENTA, EdgeType.EXCEPCIONA,
    EdgeType.ATRIBUI_RESPONSABILIDADE, EdgeType.APLICA_A, EdgeType.TENSIONA,
}

_SKIP_DOC_TYPES = {"manual"}  # manuals rarely impose obligations


def _build_edge(art_id: str, c: dict, stats: dict) -> dict | None:
    """Validate and build a single edge dict from an LLM candidate. Returns None if invalid."""
    conf = float(c.get("confidence", 0))
    etype_val = c.get("edgeType", "")
    try:
        etype = EdgeType(etype_val)
    except ValueError:
        stats["discarded"] += 1
        return None
    if etype not in _VALID_EDGE_TYPES:
        stats["discarded"] += 1
        return None
    if conf < IMPLICIT_CONFIDENCE_THRESHOLD:
        stats["discarded"] += 1
        return None
    target_id = c.get("targetId", "")
    if not target_id:
        stats["discarded"] += 1
        return None

    auto = conf >= IMPLICIT_CONFIDENCE_AUTO_APPROVE
    eid = edge_id(art_id, etype.value, target_id)
    if auto:
        stats["auto_approved"] += 1
    else:
        stats["pending_review"] += 1
    return {
        "id": eid,
        "source": art_id,
        "target": target_id,
        "type": etype.value,
        "weight": EDGE_DEFAULT_WEIGHTS.get(etype, 0.6),
        "direction": "forward",
        "implicit": True,
        "confidence": conf,
        "textEvidence": c.get("textEvidence", "")[:300],
        "description": c.get("reasoning", ""),
        "review_required": not auto,
        "deprecated": False,
        "stale": False,
    }


class ImplicationAnalyzerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("implication-analyzer")
        self._prompt = load_prompt("implication-analyzer")

    def run(self, intermediate_dir: Path, corpus_dir: Path) -> None:
        manifest_path = intermediate_dir / "corpus_scanner.json"
        if not manifest_path.exists():
            manifest_path = intermediate_dir / "scan_manifest.json"
        norm_path = intermediate_dir / "norm_analyzer.json"
        corpus_texts_path = intermediate_dir / "corpus_texts_builder.json"

        if not norm_path.exists():
            console.print("[red]ERROR:[/red] norm_analyzer.json required")
            return

        manifest = self._load_json(manifest_path) if manifest_path.exists() else {"documents": []}
        norm_data = self._load_json(norm_path)
        corpus_texts = self._load_json(corpus_texts_path)["texts"] if corpus_texts_path.exists() else {}

        # Load previous output for incremental processing
        output_path = intermediate_dir / "implication_analyzer.json"
        existing_output = self._load_json(output_path) if output_path.exists() else None

        processed_hashes: dict[str, str] = {}
        edges_by_source_doc: dict[str, list[str]] = {}  # doc_id -> [edge_ids]
        preserved_edges: list[dict] = []
        if existing_output:
            processed_hashes = existing_output.get("processedDocIds", {})
            edges_by_source_doc = existing_output.get("edgesBySourceDoc", {})
            # Current file hashes from norm_analyzer to detect changed docs
            current_hashes: dict[str, str] = norm_data.get("processedDocIds", {})
            new_or_changed = {
                doc_id for doc_id in processed_hashes
                if current_hashes.get(doc_id) != processed_hashes.get(doc_id)
            } | (set(current_hashes) - set(processed_hashes))

            for edge in existing_output.get("edges", []):
                source_doc = doc_id_from_node(edge["source"])
                if source_doc not in new_or_changed:
                    preserved_edges.append(edge)
        else:
            current_hashes = norm_data.get("processedDocIds", {})
            new_or_changed = set(current_hashes)

        # skip doc types
        skip_docs: set[str] = set()
        for doc in manifest.get("documents", []):
            if doc.get("type", "").lower() in _SKIP_DOC_TYPES:
                skip_docs.add(doc["documentId"])

        # Build article summary lookup
        art_summaries: dict[str, str] = {}
        for doc_id, doc_info in norm_data.get("byDocument", {}).items():
            for node in doc_info.get("nodes", []):
                if node.get("type") == "artigo":
                    art_summaries[node["id"]] = node.get("summary", "")

        all_edges: list[dict] = list(preserved_edges)
        stats = {"total_candidates": 0, "auto_approved": 0, "pending_review": 0, "discarded": 0}

        for doc_id, doc_info in norm_data.get("byDocument", {}).items():
            if doc_id in skip_docs:
                console.print(f"[dim]  skipping {doc_id} (manual)[/dim]")
                continue

            if doc_id not in new_or_changed:
                console.print(f"[dim]  {doc_id}: unchanged, reusing cached edges[/dim]")
                continue

            art_nodes = [n for n in doc_info.get("nodes", []) if n.get("type") == "artigo"]
            if not art_nodes:
                continue

            # Candidate summaries: all articles outside this document
            other_summaries = "\n".join(
                f"{nid}: {summ[:120]}"
                for nid, summ in art_summaries.items()
                if nid not in {n["id"] for n in art_nodes}
            )

            doc_edge_ids: list[str] = []

            # Process articles in batches
            for batch_start in range(0, len(art_nodes), IMPLICATION_BATCH_SIZE):
                batch = art_nodes[batch_start : batch_start + IMPLICATION_BATCH_SIZE]

                if IMPLICATION_BATCH_SIZE == 1 or len(batch) == 1:
                    # Single-article path: original format (array response)
                    art_node = batch[0]
                    art_id = art_node["id"]
                    art_text = corpus_texts.get(art_id, {}).get("textoCompleto", art_node.get("summary", ""))
                    if not art_text:
                        continue

                    user_prompt = (
                        f"ARTIGO FONTE:\n{art_id}: {art_text[:1200]}\n\n"
                        f"ARTIGOS CANDIDATOS (id: resumo):\n{other_summaries[:3000]}"
                    )
                    try:
                        raw = self.client.call(system=self._prompt, user=user_prompt)
                        candidates = parse_json_response(raw, self.client, art_id)
                        if not isinstance(candidates, list):
                            continue
                        stats["total_candidates"] += len(candidates)
                        candidates.sort(key=lambda x: x.get("confidence", 0), reverse=True)
                        for c in candidates[:MAX_IMPLICIT_EDGES_PER_ARTICLE]:
                            built = _build_edge(art_id, c, stats)
                            if built:
                                all_edges.append(built)
                                doc_edge_ids.append(built["id"])
                    except Exception as e:
                        console.print(f"[yellow]⚠[/yellow]  {art_id}: LLM failed: {e}")
                else:
                    # Multi-article batch: object response keyed by art_id
                    sources_text = "\n\n".join(
                        f"ARTIGO FONTE {i + 1}:\n{art['id']}: "
                        f"{corpus_texts.get(art['id'], {}).get('textoCompleto', art.get('summary', ''))[:1000]}"
                        for i, art in enumerate(batch)
                    )
                    user_prompt = (
                        f"ARTIGOS FONTE (analisar relações de cada um):\n{sources_text}\n\n"
                        f"ARTIGOS CANDIDATOS (id: resumo):\n{other_summaries[:3000]}"
                    )
                    try:
                        raw = self.client.call(system=self._prompt, user=user_prompt)
                        result = parse_json_response(raw, self.client, f"{doc_id} batch {batch_start}")

                        # Support both object (new) and array (fallback for single art in batch)
                        if isinstance(result, list):
                            result = {batch[0]["id"]: result} if len(batch) == 1 else {}

                        if not isinstance(result, dict):
                            continue

                        for art_node in batch:
                            art_id = art_node["id"]
                            candidates = result.get(art_id, [])
                            if not isinstance(candidates, list):
                                continue
                            stats["total_candidates"] += len(candidates)
                            candidates.sort(key=lambda x: x.get("confidence", 0), reverse=True)
                            for c in candidates[:MAX_IMPLICIT_EDGES_PER_ARTICLE]:
                                built = _build_edge(art_id, c, stats)
                                if built:
                                    all_edges.append(built)
                                    doc_edge_ids.append(built["id"])
                    except Exception as e:
                        console.print(f"[yellow]⚠[/yellow]  {doc_id} batch {batch_start}: LLM failed: {e}")

            edges_by_source_doc[doc_id] = doc_edge_ids
            processed_hashes[doc_id] = current_hashes.get(doc_id, "")

        output = {
            "generatedAt": datetime.now().isoformat(),
            "edges": all_edges,
            "stats": stats,
            "processedDocIds": processed_hashes,
            "edgesBySourceDoc": edges_by_source_doc,
        }
        self._save_json(intermediate_dir / "implication_analyzer.json", output)
        console.print(
            f"[green]✓[/green] implication-analyzer: {len(all_edges)} edges "
            f"({stats['auto_approved']} auto, {stats['pending_review']} review, {stats['discarded']} discarded)"
        )
