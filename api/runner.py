from __future__ import annotations
import asyncio
import json
import queue
import threading
from typing import AsyncGenerator


_runs: dict[str, dict] = {}


def start_run(run_id: str) -> None:
    q: queue.Queue = queue.Queue()
    _runs[run_id] = {"status": "running", "queue": q}
    threading.Thread(target=_execute, args=(run_id, q), daemon=True).start()


def _execute(run_id: str, q: queue.Queue) -> None:
    def callback(event: dict) -> None:
        q.put(event)

    try:
        from pipeline.run import run_pipeline_with_callback
        run_pipeline_with_callback(run_id, callback)
        _runs[run_id]["status"] = "done"
        q.put({"type": "done"})
    except Exception as e:
        _runs[run_id]["status"] = "error"
        q.put({"type": "error", "message": str(e)})


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
