#!/bin/sh
set -e
mkdir -p /app/data
alembic upgrade head
python -c "from db.legislacao import legislacao_enabled, init_legislacao_db; legislacao_enabled() and init_legislacao_db()"
exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 1
