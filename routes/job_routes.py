from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from src import bg_jobs


def _tail(path: str | None, max_chars: int = 2000) -> str:
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:].rstrip()


def _job_view(rec: dict) -> dict:
    started = rec.get("started_at", rec.get("started"))
    elapsed = None
    if started:
        end = rec.get("ended_at") or time.time()
        elapsed = max(0.0, round(end - float(started), 3))
    out = dict(rec)
    if out.get("killed"):
        out["status"] = "killed"
    out["elapsed_s"] = elapsed
    out["output_tail"] = _tail(rec.get("log_path"))
    return out


def _filtered_jobs(session_id: str | None, run_id: str | None, profile_id: str | None) -> list[dict]:
    jobs = bg_jobs.refresh()
    rows = []
    for rec in jobs.values():
        if session_id and rec.get("session_id") != session_id:
            continue
        if run_id and rec.get("run_id") != run_id:
            continue
        if profile_id and rec.get("profile_id") != profile_id:
            continue
        rows.append(_job_view(rec))
    return sorted(rows, key=lambda r: r.get("started_at", r.get("started", 0)) or 0, reverse=True)


def setup_job_routes() -> APIRouter:
    router = APIRouter(prefix="/api/jobs", tags=["jobs"])

    @router.get("")
    def list_jobs(
        session_id: str | None = Query(default=None),
        run_id: str | None = Query(default=None),
        profile_id: str | None = Query(default=None),
    ):
        return {"jobs": _filtered_jobs(session_id, run_id, profile_id)}

    @router.get("/{job_id}")
    def get_job(job_id: str):
        rec = bg_jobs.get(job_id)
        if not rec:
            raise HTTPException(status_code=404, detail="unknown job")
        return {"job": _job_view(rec)}

    @router.post("/{job_id}/stop")
    def stop_job(job_id: str):
        rec = bg_jobs.kill(job_id)
        if not rec:
            raise HTTPException(status_code=404, detail="unknown job")
        return {"job": _job_view(rec)}

    return router
