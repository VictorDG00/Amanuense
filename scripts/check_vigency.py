#!/usr/bin/env python3
"""
Weekly cron job: report nodes with stale vigency or approaching dataFim.

Usage: python scripts/check_vigency.py [output/vigency-index.json]
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path


STALENESS_DAYS = 90
EXPIRY_WARN_DAYS = 30


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/vigency-index.json")
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        return 1

    data = json.loads(path.read_text())
    today = date.today()
    warnings = []

    for entry in data.get("entries", []):
        node_id = entry["nodeId"]
        last_checked = date.fromisoformat(entry.get("ultimaVerificacao", "2000-01-01"))
        data_fim = entry.get("dataFim")

        if (today - last_checked).days > STALENESS_DAYS:
            warnings.append(
                f"STALE  {node_id} — last checked {last_checked} "
                f"({(today - last_checked).days} days ago)"
            )

        if data_fim:
            fim = date.fromisoformat(data_fim)
            days_left = (fim - today).days
            if 0 <= days_left <= EXPIRY_WARN_DAYS:
                warnings.append(f"EXPIRING {node_id} — expires {fim} ({days_left} days)")

    if warnings:
        for w in warnings:
            print(w)
        return 1

    print(f"OK — {len(data.get('entries', []))} nodes checked, none stale.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
