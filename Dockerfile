# ── API ────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS api
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[api]"
COPY pipeline/ pipeline/
COPY api/ api/
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

# ── Web ────────────────────────────────────────────────────────────────────────
FROM nginx:alpine AS web
COPY frontend/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
