from __future__ import annotations
import json
from pathlib import Path
from abc import ABC, abstractmethod
from rich.console import Console
from ..utils.claude_client import ClaudeClient

console = Console()


def load_prompt(agent_name: str) -> str:
    prompt_path = Path(__file__).parent.parent / "prompts" / f"{agent_name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


class BaseAgent(ABC):
    def __init__(self, name: str) -> None:
        self.name = name
        self.client = ClaudeClient()

    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_json(self, path: Path, data: dict | list) -> None:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        console.print(f"[green]✓[/green] {self.name}: saved {path.name}")

    @abstractmethod
    def run(self, intermediate_dir: Path, corpus_dir: Path) -> None: ...
