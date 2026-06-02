from __future__ import annotations
from datetime import datetime
from pathlib import Path
import click
from rich.console import Console
from dotenv import load_dotenv

load_dotenv()
console = Console()

AGENT_SEQUENCE = [
    "corpus-scanner",
    "norm-analyzer",
    "hierarchy-analyzer",
    "revocation-analyzer",
    "implication-analyzer",
    "domain-analyzer",
    "graph-reviewer",
    "tour-builder",
]


@click.group()
def cli() -> None:
    """Amanuense — pipeline de grafos de conhecimento jurídico."""


@cli.command()
@click.option("--agent", default=None, help="Run only this agent")
@click.option("--run-id", default=None, help="Resume existing run by ID")
@click.option("--resume", is_flag=True, help="Skip agents with existing output")
@click.option("--file", default=None, help="Process only this corpus file (by name)")
def run(agent: str | None, run_id: str | None, resume: bool, file: str | None) -> None:
    """Run the full pipeline or a single agent."""
    from .config import INTERMEDIATE_DIR, OUTPUT_DIR

    run_id = run_id or datetime.now().strftime("%Y%m%dT%H%M%S")
    intermediate_dir = INTERMEDIATE_DIR / run_id
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold blue]run-id:[/bold blue] {run_id}")

    agents_to_run = [agent] if agent else AGENT_SEQUENCE

    for agent_name in agents_to_run:
        output_file = intermediate_dir / f"{agent_name.replace('-', '_')}.json"
        if resume and output_file.exists():
            console.print(f"[yellow]↷[/yellow] skipping {agent_name} (output exists)")
            continue
        _run_agent(agent_name, intermediate_dir)

    console.print("[bold green]Done.[/bold green]")


def _run_agent(name: str, intermediate_dir: Path) -> None:
    from .config import CORPUS_DIR
    console.print(f"[bold]→[/bold] {name}")

    if name == "corpus-scanner":
        from .agents.corpus_scanner import CorpusScannerAgent
        CorpusScannerAgent().run(intermediate_dir, CORPUS_DIR)
    else:
        console.print(f"[dim]  (agent '{name}' not yet implemented)[/dim]")


@cli.command()
@click.argument("graph_path", default="output/knowledge-graph.json")
def validate(graph_path: str) -> None:
    """Validate a knowledge-graph.json file."""
    import json, sys
    path = Path(graph_path)
    if not path.exists():
        console.print(f"[red]ERROR:[/red] {path} not found")
        sys.exit(1)
    data = json.loads(path.read_text())
    node_ids = {n["id"] for n in data.get("nodes", [])}
    errors = []
    for edge in data.get("edges", []):
        if edge["source"] not in node_ids:
            errors.append(f"Dangling source: {edge['source']}")
        if edge["target"] not in node_ids:
            errors.append(f"Dangling target: {edge['target']}")
    review_count = sum(
        1 for x in data.get("nodes", []) + data.get("edges", [])
        if x.get("review_required")
    )
    if errors:
        for e in errors:
            console.print(f"[red]ERROR:[/red] {e}")
        sys.exit(1)
    console.print(
        f"[green]OK[/green] — {len(node_ids)} nodes, "
        f"{len(data.get('edges', []))} edges, "
        f"{review_count} pending review"
    )


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
