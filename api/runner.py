from __future__ import annotations
import asyncio
import json
import queue
import threading
from datetime import datetime
from typing import AsyncGenerator


_runs: dict[str, dict] = {}


def start_run(run_id: str) -> None:
    q: queue.Queue = queue.Queue()
    _runs[run_id] = {"status": "running", "queue": q}
    threading.Thread(target=_execute, args=(run_id, q), daemon=True).start()


def _execute(run_id: str, q: queue.Queue) -> None:
    def callback(event: dict) -> None:
        q.put(event)

    error_msg: str | None = None
    try:
        from pipeline.run import run_pipeline_with_callback
        run_pipeline_with_callback(run_id, callback)
        _runs[run_id]["status"] = "done"
        q.put({"type": "done"})
    except Exception as e:
        error_msg = str(e)
        _runs[run_id]["status"] = "error"
        q.put({"type": "error", "message": error_msg})
    finally:
        _update_run_record(run_id, error_msg)


def _update_run_record(run_id: str, error_msg: str | None) -> None:
    try:
        from db.session import SessionLocal
        from db.models import PipelineRun
        with SessionLocal() as db:
            run = db.get(PipelineRun, run_id)
            if run:
                run.status = "error" if error_msg else "done"
                run.finished_at = datetime.utcnow()
                run.error_message = error_msg
                db.commit()
    except Exception:
        pass  # DB update is best-effort; don't crash the pipeline thread


async def stream_events(run_id: str) -> AsyncGenerator[str, None]:
    if run_id not in _runs:
        yield f"data: {json.dumps({'type': 'error', 'message': 'run not found'})}\n\n"
        return

    run = _runs[run_id]
    q = run["queue"]

    while True:
        try:
            event = q.get_nowait()
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in ("done", "error"):
                break
        except queue.Empty:
            if run["status"] in ("done", "error"):
                break
            await asyncio.sleep(0.2)
            yield ": keepalive\n\n"
