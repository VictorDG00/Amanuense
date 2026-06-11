"""Conexão e bootstrap da Base de Legislação Estruturada (PostgreSQL).

O DDL canônico mora em ``db/sql/`` (01_schema.sql, 02_versionamento.sql) e é
aplicado aqui de forma idempotente — nunca via ORM/Alembic. Toda mutação de
dados passa pelas funções plpgsql do motor (fn_criar_norma, fn_inserir_dispositivo,
fn_registrar_alteracao, fn_registrar_revogacao); INSERT direto nas tabelas de
versão é proibido.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

SQL_DIR = Path(__file__).parent / "sql"
SCHEMA_FILES = ["01_schema.sql", "02_versionamento.sql"]
DEMO_FILE = "03_demo_lgpd.sql"

def database_url() -> str:
    """Lê a URL em tempo de chamada (depois de load_dotenv), não no import."""
    return os.environ.get("LEGISLACAO_DATABASE_URL", "")


def legislacao_enabled() -> bool:
    """True quando a base estruturada está configurada (modo fonte da verdade)."""
    return bool(database_url())


def get_conn():
    """Abre uma conexão psycopg3 com a base de legislação (autocommit off)."""
    import psycopg

    url = database_url()
    if not url:
        raise RuntimeError(
            "LEGISLACAO_DATABASE_URL não definida — a base de legislação "
            "estruturada está desabilitada (modo legado)."
        )
    return psycopg.connect(url)


def _executable_sql(text: str) -> str:
    """Remove a parte não executável de scripts escritos para o psql.

    O 03_demo_lgpd.sql é vendorizado verbatim, mas contém meta-comandos
    (\\echo) e blocos demonstrativos BEGIN/ROLLBACK que só fazem sentido no
    psql. Para a carga via driver, só o bloco de seed (tudo antes do primeiro
    meta-comando) é executado.
    """
    lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("\\"):
            break
        lines.append(line)
    return "\n".join(lines)


def _applied_files(conn) -> set[str]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS legislacao_schema_version (
            filename   TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    rows = conn.execute("SELECT filename FROM legislacao_schema_version").fetchall()
    return {r[0] for r in rows}


def init_legislacao_db(with_demo: bool = False) -> list[str]:
    """Aplica os SQLs de db/sql/ ainda não registrados. Idempotente.

    Retorna a lista de arquivos aplicados nesta chamada.
    """
    files = list(SCHEMA_FILES) + ([DEMO_FILE] if with_demo else [])
    applied_now: list[str] = []

    with get_conn() as conn:
        already = _applied_files(conn)
        conn.commit()
        for filename in files:
            if filename in already:
                continue
            sql = (SQL_DIR / filename).read_text(encoding="utf-8")
            if filename == DEMO_FILE:
                sql = _executable_sql(sql)
            try:
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO legislacao_schema_version (filename, applied_at) "
                    "VALUES (%s, %s)",
                    (filename, datetime.now(timezone.utc)),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            applied_now.append(filename)
    return applied_now
