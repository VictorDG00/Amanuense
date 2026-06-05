from __future__ import annotations
from datetime import datetime
from pathlib import Path
from .base import BaseAgent, load_prompt, console
from ..schemas import EdgeType, EDGE_DEFAULT_WEIGHTS
from ..utils.id_factory import edge_id
from ..utils.llm_helpers import parse_json_response
from ..config import IMPLICIT_CONFIDENCE_THRESHOLD, IMPLICIT_CONFIDENCE_AUTO_APPROVE, MAX_IMPLICIT_EDGES_PER_ARTICLE

_VALID_EDGE_TYPES = {
    EdgeType.OBRIGA, EdgeType.PERMITE, EdgeType.PROIBE, EdgeType.DEFINE,
    EdgeType.CONDICIONA, EdgeType.COMPLEMENTA, EdgeType.EXCEPCIONA,
    EdgeType.ATRIBUI_RESPONSABILIDADE, EdgeType.APLICA_A, EdgeType.TENSIONA,
}

_SKIP_DOC_TYPES = {"manual"}  # manuals rarely impose obligations


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

        all_edges: list[dict] = []
        stats = {"total_candidates": 0, "auto_approved": 0, "pending_review": 0, "discarded": 0}

        for doc_id, doc_info in norm_data.get("byDocument", {}).items():
            if doc_id in skip_docs:
                console.print(f"[dim]  skipping {doc_id} (manual)[/dim]")
                continue

            art_nodes = [n for n in doc_info.get("nodes", []) if n.get("type") == "artigo"]
            if not art_nodes:
                continue

            # build candidate summaries (all articles except source)
            other_summaries = "\n".join(
                f"{nid}: {summ[:120]}"
                for nid, summ in art_summaries.items()
                if nid not in {n["id"] for n in art_nodes}
            )

            for art_node in art_nodes:
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

                    # filter and cap
                    valid: list[dict] = []
                    for c in candidates:
                        stats["total_candidates"] += 1
                        conf = float(c.get("confidence", 0))
                        etype_val = c.get("edgeType", "")
                        try:
                            etype = EdgeType(etype_val)
                        except ValueError:
                            stats["discarded"] += 1
                            continue
                        if etype not in _VALID_EDGE_TYPES:
                            stats["discarded"] += 1
                            continue
                        if conf < IMPLICIT_CONFIDENCE_THRESHOLD:
                            stats["discarded"] += 1
                            continue
                        valid.append(c)

                    valid.sort(key=lambda x: x.get("confidence", 0), reverse=True)
                    valid = valid[:MAX_IMPLICIT_EDGES_PER_ARTICLE]

                    for c in valid:
                        conf = float(c.get("confidence", 0))
                        etype = EdgeType(c["edgeType"])
                        target_id = c.get("targetId", "")
                        if not target_id:
                            continue
                        auto = conf >= IMPLICIT_CONFIDENCE_AUTO_APPROVE
                        needs_review = not auto

                        eid = edge_id(art_id, etype.value, target_id)
                        all_edges.append({
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
                            "review_required": needs_review,
                            "deprecated": False,
                            "stale": False,
                        })
                        if auto:
                            stats["auto_approved"] += 1
                        else:
                            stats["pending_review"] += 1

                except Exception as e:
                    console.print(f"[yellow]⚠[/yellow]  {art_id}: LLM failed: {e}")

        output = {
            "generatedAt": datetime.now().isoformat(),
            "edges": all_edges,
            "stats": stats,
        }
        self._save_json(intermediate_dir / "implication_analyzer.json", output)
        console.print(
            f"[green]✓[/green] implication-analyzer: {len(all_edges)} edges "
            f"({stats['auto_approved']} auto, {stats['pending_review']} review, {stats['discarded']} discarded)"
        )
