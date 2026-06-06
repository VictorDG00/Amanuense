from __future__ import annotations
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

BASE_DIR = Path(__file__).parent.parent
_DEFAULT_DB_PATH = BASE_DIR / "data" / "amanuense.db"

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{_DEFAULT_DB_PATH}",
)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Run Alembic migrations to head on startup."""
    from alembic.config import Config
    from alembic import command

    _DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    alembic_cfg = Config(str(BASE_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")
