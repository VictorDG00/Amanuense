from __future__ import annotations
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

_DEFAULT_DB = Path(__file__).parent.parent.parent / ".cache" / "llm_responses.db"


def _key(system: str, user: str) -> str:
    return hashlib.sha256(f"{system}\x00{user}".encode("utf-8")).hexdigest()


class LLMCache:
    def __init__(self, db_path: Path = _DEFAULT_DB, ttl_days: int = 30) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS responses "
            "(key TEXT PRIMARY KEY, response TEXT, created_at TEXT)"
        )
        self._conn.commit()
        self._ttl = timedelta(days=ttl_days)

    def get(self, system: str, user: str) -> str | None:
        key = _key(system, user)
        row = self._conn.execute(
            "SELECT response, created_at FROM responses WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        created = datetime.fromisoformat(row[1])
        if datetime.now() - created > self._ttl:
            self._conn.execute("DELETE FROM responses WHERE key = ?", (key,))
            self._conn.commit()
            return None
        return row[0]

    def set(self, system: str, user: str, response: str) -> None:
        key = _key(system, user)
        self._conn.execute(
            "INSERT OR REPLACE INTO responses (key, response, created_at) VALUES (?, ?, ?)",
            (key, response, datetime.now().isoformat()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
