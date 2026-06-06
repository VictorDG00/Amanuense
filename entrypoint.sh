#!/bin/sh
set -e
mkdir -p /app/data
alembic upgrade head
exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 1
