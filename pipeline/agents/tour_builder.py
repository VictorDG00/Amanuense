from __future__ import annotations
import json
from pathlib import Path
from .base import BaseAgent, load_prompt, console
from ..utils.llm_helpers import parse_json_response
from ..config import OUTPUT_DIR


class TourBuilderAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("tour-builder")
        self._prompt = load_prompt("tour-builder")

    def run(self, intermediate_dir: Path, corpus_dir: Path) -> None:
        graph_path = OUTPUT_DIR / "knowledge-graph.json"
        if not graph_path.exists():
            console.print("[red]ERROR:[/red] knowledge-graph.json not found — run graph-builder first")
            return

        data = json.loads(graph_path.read_text(encoding="utf-8"))
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        # Build compact summary for LLM
        nodes_summary = [
            {"id": n["id"], "name": n.get("name", ""), "summary": n.get("summary", "")[:100], "tags": n.get("tags", [])}
            for n in nodes[:80]  # limit to avoid token overflow
        ]
        edges_sample = [
            {"source": e["source"], "target": e["target"], "type": e["type"], "description": e.get("description", "")[:60]}
            for e in edges[:40]
        ]

        user_prompt = json.dumps({
            "nodes_summary": nodes_summary,
            "edges_sample": edges_sample,
            "corpus": "Pix — BCB",
        }, ensure_ascii=False)

        tours: list[dict] = []
        try:
            raw = self.client.call(system=self._prompt, user=user_prompt)
            parsed = parse_json_response(raw, self.client, "tour-builder")
            if isinstance(parsed, list):
                tours = parsed
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow]  tour-builder LLM failed: {e}")
            tours = self._fallback_tours(nodes)

        # Validate node references
        known_ids = {n["id"] for n in nodes}
        for tour in tours:
            for step in tour.get("steps", []):
                step["nodeIds"] = [nid for nid in step.get("nodeIds", []) if nid in known_ids]

        data["tours"] = tours
        graph_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        console.print(f"[green]✓[/green] tour-builder: {len(tours)} tours criados")

    def _fallback_tours(self, nodes: list[dict]) -> list[dict]:
        norma_ids = [n["id"] for n in nodes if n.get("type") == "norma"]
        art_ids = [n["id"] for n in nodes if n.get("type") == "artigo"][:5]
        return [
            {
                "id": "tour-fundamentos-pix",
                "title": "Fundamentos do Pix",
                "description": "Roteiro introdutório ao ecossistema regulatório Pix.",
                "profileTarget": ["advogado", "compliance", "gestor"],
                "steps": [
                    {"order": 1, "title": "As Normas Fundantes", "description": "As normas que instituem o arranjo Pix.", "nodeIds": norma_ids[:3]},
                    {"order": 2, "title": "Primeiros Artigos", "description": "Artigos fundantes do Regulamento Pix.", "nodeIds": art_ids},
                ],
            },
        ]
