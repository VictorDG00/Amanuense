from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from rich.console import Console
from ..schemas import (
    GraphNode, GraphEdge, KnowledgeGraph, Layer, TourStep,
    NodeType, VigencyStatus, VigenciaMeta, NormativeLayer,
)
from .vigency import apply_vigency_updates, propagate_revocation, build_vigency_index, build_diff_log
from .exporter import to_json, write_js_data, build_corpus_texts
from ..config import OUTPUT_DIR

console = Console()


class GraphBuilder:
    def __init__(self, intermediate_dir: Path) -> None:
        self.intermediate_dir = intermediate_dir
        self._nodes: list[GraphNode] = []
        self._edges: list[GraphEdge] = []
        self._layers: list[Layer] = []
        self._vigency_updates: list[dict] = []
        self._diff_log_entries: list[dict] = []

    def _load(self, name: str) -> dict | None:
        path = self.intermediate_dir / name
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def load_agents(self) -> None:
        # 1. norm nodes
        norm_data = self._load("norm_analyzer.json")
        if norm_data:
            for doc_id, doc_info in norm_data.get("byDocument", {}).items():
                for n in doc_info.get("nodes", []):
                    try:
                        self._nodes.append(GraphNode.model_validate(n))
                    except Exception as e:
                        console.print(f"[yellow]⚠[/yellow]  skipping node {n.get('id','?')}: {e}")

        # 2. domain nodes
        domain_data = self._load("domain_analyzer.json")
        if domain_data:
            for n in domain_data.get("nodes", []):
                try:
                    self._nodes.append(GraphNode.model_validate(n))
                except Exception as e:
                    console.print(f"[yellow]⚠[/yellow]  skipping domain node {n.get('id','?')}: {e}")
            for e in domain_data.get("edges", []):
                try:
                    self._edges.append(GraphEdge.model_validate(e))
                except Exception as ex:
                    console.print(f"[yellow]⚠[/yellow]  skipping domain edge: {ex}")

        # 3. hierarchy edges + layers
        hier_data = self._load("hierarchy_analyzer.json")
        if hier_data:
            for e in hier_data.get("edges", []):
                try:
                    self._edges.append(GraphEdge.model_validate(e))
                except Exception as ex:
                    console.print(f"[yellow]⚠[/yellow]  skipping hierarchy edge: {ex}")
            for layer_dict in hier_data.get("layers", []):
                try:
                    self._layers.append(Layer.model_validate(layer_dict))
                except Exception as ex:
                    console.print(f"[yellow]⚠[/yellow]  skipping layer: {ex}")

        # 4. revocation edges
        rev_data = self._load("revocation_analyzer.json")
        if rev_data:
            for e in rev_data.get("edges", []):
                try:
                    self._edges.append(GraphEdge.model_validate(e))
                except Exception as ex:
                    console.print(f"[yellow]⚠[/yellow]  skipping revocation edge: {ex}")
            self._vigency_updates.extend(rev_data.get("vigencyUpdates", []))
            self._diff_log_entries.extend(rev_data.get("diffLogEntries", []))

        # 5. implication edges
        impl_data = self._load("implication_analyzer.json")
        if impl_data:
            for e in impl_data.get("edges", []):
                try:
                    self._edges.append(GraphEdge.model_validate(e))
                except Exception as ex:
                    console.print(f"[yellow]⚠[/yellow]  skipping implication edge: {ex}")

    def apply_vigency_updates(self) -> None:
        self._nodes = apply_vigency_updates(self._nodes, self._vigency_updates)

    def _deduplicate(self) -> None:
        # nodes: last-writer wins, review_required is OR'd
        seen_nodes: dict[str, GraphNode] = {}
        for node in self._nodes:
            if node.id in seen_nodes:
                existing = seen_nodes[node.id]
                if existing.review_required or node.review_required:
                    node.review_required = True
            seen_nodes[node.id] = node
        self._nodes = list(seen_nodes.values())

        # edges: deduplicate by id
        seen_edges: dict[str, GraphEdge] = {}
        for edge in self._edges:
            seen_edges[edge.id] = edge
        self._edges = list(seen_edges.values())

    def build(self) -> KnowledgeGraph:
        self._deduplicate()

        # Update layer nodeIds to reflect actual deduplicated node set
        node_ids = {n.id for n in self._nodes}
        for layer in self._layers:
            layer.nodeIds = [nid for nid in layer.nodeIds if nid in node_ids]

        graph = KnowledgeGraph(
            generatedAt=datetime.now(),
            corpus="pix-bcb",
            nodes=self._nodes,
            edges=self._edges,
            layers=self._layers,
            tours=[],
        )

        graph = propagate_revocation(graph)
        return graph

    def validate(self, graph: KnowledgeGraph) -> list[str]:
        errors: list[str] = []
        node_ids = {n.id for n in graph.nodes}
        for edge in graph.edges:
            if edge.source not in node_ids:
                errors.append(f"Dangling source: {edge.source} in edge {edge.id}")
            if edge.target not in node_ids:
                errors.append(f"Dangling target: {edge.target} in edge {edge.id}")
        return errors

    def save(self, graph: KnowledgeGraph, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. knowledge-graph.json
        to_json(graph, output_dir / "knowledge-graph.json")
        console.print(f"[green]✓[/green] {output_dir}/knowledge-graph.json")

        # 2. vigency-index.json
        vi = build_vigency_index(graph, graph.corpus)
        (output_dir / "vigency-index.json").write_text(
            json.dumps(vi.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        console.print(f"[green]✓[/green] {output_dir}/vigency-index.json")

        # 3. diff-log.json
        dl = build_diff_log(self._diff_log_entries)
        (output_dir / "diff-log.json").write_text(
            json.dumps(dl.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        console.print(f"[green]✓[/green] {output_dir}/diff-log.json")

        # 4. corpus-texts.json
        ct = build_corpus_texts(self.intermediate_dir, graph)
        (output_dir / "corpus-texts.json").write_text(
            json.dumps(ct, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        console.print(f"[green]✓[/green] {output_dir}/corpus-texts.json")

        # 5. graph-data.js for frontend
        write_js_data(graph, output_dir)
        console.print(f"[green]✓[/green] {output_dir}/graph-data.js")

        # 6. vigency-data.js for frontend
        vi_js = (
            f"// Auto-generated by Amanuense graph-builder\n"
            f"window.VIGENCY_DATA = {json.dumps(vi.model_dump(mode='json'), ensure_ascii=False, indent=2, default=str)};\n"
        )
        (output_dir / "vigency-data.js").write_text(vi_js, encoding="utf-8")
        console.print(f"[green]✓[/green] {output_dir}/vigency-data.js")
