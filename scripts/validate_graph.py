#!/usr/bin/env python3
"""Validate output/knowledge-graph.json. Exit 1 on critical errors."""
import json
import sys
from pathlib import Path


def main() -> int:
    graph_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/knowledge-graph.json")
    if not graph_path.exists():
        print(f"ERROR: {graph_path} not found", file=sys.stderr)
        return 1

    data = json.loads(graph_path.read_text())
    node_ids = {n["id"] for n in data.get("nodes", [])}
    errors = []

    for edge in data.get("edges", []):
        if edge["source"] not in node_ids:
            errors.append(f"Dangling edge source: {edge['source']} in {edge['id']}")
        if edge["target"] not in node_ids:
            errors.append(f"Dangling edge target: {edge['target']} in {edge['id']}")

    review_required = [
        x["id"] for x in data.get("nodes", []) + data.get("edges", [])
        if x.get("review_required")
    ]

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"OK — {len(node_ids)} nodes, {len(data.get('edges', []))} edges")
    if review_required:
        print(f"WARN — {len(review_required)} items pending human review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
