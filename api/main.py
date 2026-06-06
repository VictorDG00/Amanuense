from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from pipeline.config import CORPUS_DIR, OUTPUT_DIR
from pipeline.corpus_registry import detect_metadata, load_registry, save_registry
from api.runner import start_run, stream_events

app = FastAPI(title="Amanuense API")


@app.get("/api/corpus")
def list_corpus():
    registry = load_registry(CORPUS_DIR)
    docs = []
    for doc_id, meta in registry.items():
        parsed_path = CORPUS_DIR / "parsed" / f"{doc_id}.md"
        docs.append({"id": doc_id, "parsed": parsed_path.exists(), **meta})
    return {"documents": docs}


@app.post("/api/corpus/upload")
async def upload_corpus(files: list[UploadFile] = File(...)):
    registry = load_registry(CORPUS_DIR)
    raw_dir = CORPUS_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    added = []
    for file in files:
        stem = Path(file.filename).stem
        doc_id = stem.lower().replace("_", "-")
        dest = raw_dir / f"{doc_id}.pdf"
        dest.write_bytes(await file.read())
        meta = detect_metadata(stem)
        registry[doc_id] = meta
        added.append({"id": doc_id, **meta})

    save_registry(CORPUS_DIR, registry)
    return {"added": added}


@app.delete("/api/corpus/{doc_id}")
def remove_corpus(doc_id: str):
    registry = load_registry(CORPUS_DIR)
    if doc_id not in registry:
        raise HTTPException(404, "Document not found")

    del registry[doc_id]
    save_registry(CORPUS_DIR, registry)

    for path in [
        CORPUS_DIR / "raw" / f"{doc_id}.pdf",
        CORPUS_DIR / "parsed" / f"{doc_id}.md",
    ]:
        if path.exists():
            path.unlink()

    return {"deleted": doc_id}


@app.post("/api/run")
def run_pipeline():
    registry = load_registry(CORPUS_DIR)
    if not registry:
        raise HTTPException(400, "Corpus vazio — faça upload de documentos primeiro")
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    start_run(run_id)
    return {"run_id": run_id}


@app.get("/api/status/{run_id}")
async def get_status(run_id: str):
    async def generator():
        async for chunk in stream_events(run_id):
            yield chunk

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/graph")
def get_graph():
    graph_path = OUTPUT_DIR / "knowledge-graph.json"
    if not graph_path.exists():
        raise HTTPException(404, "Nenhum grafo encontrado — execute o pipeline primeiro")
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    if not data.get("nodes"):
        raise HTTPException(404, "Grafo vazio — execute o pipeline primeiro")
    return JSONResponse(data)
