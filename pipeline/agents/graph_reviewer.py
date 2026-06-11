from __future__ import annotations
import json
import sys
from pathlib import Path
from .base import BaseAgent, console
from ..config import OUTPUT_DIR


class GraphReviewerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("graph-reviewer")

    def run(self, intermediate_dir: Path, corpus_dir: Path) -> None:
        graph_path = OUTPUT_DIR / "knowledge-graph.json"
        if not graph_path.exists():
            console.print("[red]ERROR:[/red] knowledge-graph.json not found — run graph-builder first")
            return
        self._review(graph_path, auto_approve_above=0.85, interactive=sys.stdin.isatty())

    def _review(self, graph_path: Path, auto_approve_above: float, interactive: bool) -> None:
        from rich.panel import Panel

        data = json.loads(graph_path.read_text(encoding="utf-8"))
        edges = data.get("edges", [])
        nodes_by_id = {n["id"]: n for n in data.get("nodes", [])}

        flagged_edges = [e for e in edges if e.get("review_required")]
        console.print(f"[bold]graph-reviewer:[/bold] {len(flagged_edges)} edges flagged for review")

        approved = rejected = skipped = 0

        for edge in flagged_edges:
            conf = edge.get("confidence", 0) or 0

            # Auto-approve high-confidence implicit edges
            if conf >= auto_approve_above:
                edge["review_required"] = False
                approved += 1
                continue

            if not interactive:
                skipped += 1
                continue

            src = nodes_by_id.get(edge["source"], {})
            tgt = nodes_by_id.get(edge["target"], {})
            evidence = edge.get("textEvidence") or edge.get("description") or "(no evidence)"

            console.print(Panel(
                f"[bold cyan]Tipo:[/bold cyan] {edge['type']}  "
                f"[bold]Confidence:[/bold] {conf:.2f}\n"
                f"[bold]Fonte:[/bold] {src.get('name', edge['source'])}\n"
                f"[bold]Alvo:[/bold] {tgt.get('name', edge['target'])}\n"
                f"[bold]Evidência:[/bold] {evidence[:300]}",
                title="Aresta para revisão",
            ))

            while True:
                choice = input("[A]provar / [R]ejeitar / [E]ditar / [S]kip / [Q]uit > ").strip().upper()
                if choice == "A":
                    edge["review_required"] = False
                    approved += 1
                    break
                elif choice == "R":
                    edge["deprecated"] = True
                    edge["review_required"] = False
                    rejected += 1
                    break
                elif choice == "E":
                    desc = input("Nova descrição: ").strip()
                    if desc:
                        edge["description"] = desc
                    edge["review_required"] = False
                    approved += 1
                    break
                elif choice == "S":
                    skipped += 1
                    break
                elif choice == "Q":
                    console.print("[yellow]Saindo da revisão.[/yellow]")
                    graph_path.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )
                    return

        graph_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        console.print(
            f"[green]✓[/green] graph-reviewer: {approved} aprovadas, {rejected} rejeitadas, {skipped} puladas"
        )
