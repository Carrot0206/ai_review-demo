"""异步规则引擎审核 API。"""
from __future__ import annotations

import asyncio
import json
from collections import Counter

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..models.schemas import ReviewStart
from ..services.material_store import resolve_review_materials
from ..services.review_engine import TASK_MANAGER, TERMINAL_STATUSES, create_review, get_review_result
from ..storage import database


router = APIRouter(prefix="/api/rule-engine", tags=["rule-engine"])


def _task_or_404(task_id: str) -> dict:
    task = database.get_task_row(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"审核任务 {task_id} 不存在")
    return task


@router.post("/reviews", status_code=202)
async def start_review(payload: ReviewStart):
    try:
        materials = (
            resolve_review_materials(payload.file_ids, payload.process)
            if payload.file_ids
            else payload.materials
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        task_id, snapshot = create_review(payload.process, materials)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    TASK_MANAGER.start(task_id)
    return {
        "task_id": task_id,
        "snapshot_id": snapshot.snapshot_id,
        "status": "queued",
        "rule_count": len(snapshot.rules),
        "snapshot_sha256": snapshot.sha256,
    }


@router.get("/reviews/{task_id}")
def get_review(task_id: str):
    task = _task_or_404(task_id)
    snapshot = database.get_snapshot(task["snapshot_id"])
    if snapshot is None:
        raise HTTPException(status_code=500, detail="审核任务的规则快照不存在")
    counts = Counter(result.status for result in database.load_rule_results(task_id))
    completed = sum(counts.values())
    return {
        "task_id": task_id,
        "process": task["process"],
        "snapshot_id": task["snapshot_id"],
        "status": task["status"],
        "rule_count": len(snapshot.rules),
        "completed_rule_count": completed,
        "progress_percent": round(completed * 100 / len(snapshot.rules), 2) if snapshot.rules else 0,
        "status_counts": {
            "passed": counts["passed"],
            "failed": counts["failed"],
            "not_applicable": counts["not_applicable"],
            "undetermined": counts["undetermined"],
            "error": counts["error"],
        },
        "created_at": task["created_at"],
        "started_at": task["started_at"],
        "finished_at": task["finished_at"],
        "error": task["error"],
    }


@router.get("/reviews/{task_id}/result")
def get_result(task_id: str):
    _task_or_404(task_id)
    result = get_review_result(task_id)
    if result is None:
        raise HTTPException(status_code=500, detail="审核结果读取失败")
    return result


@router.get("/reviews/{task_id}/events")
async def stream_events(
    task_id: str,
    request: Request,
    last_event_id: int = Header(default=0, alias="Last-Event-ID"),
):
    _task_or_404(task_id)

    async def event_stream():
        cursor = max(0, last_event_id)
        while True:
            if await request.is_disconnected():
                break
            events = database.load_events(task_id, cursor)
            for event in events:
                cursor = event["event_id"]
                payload = json.dumps(event["data"], ensure_ascii=False, separators=(",", ":"))
                yield f"id: {cursor}\nevent: {event['event_type']}\ndata: {payload}\n\n"
            task = database.get_task_row(task_id)
            if task is None or (task["status"] in TERMINAL_STATUSES and not events):
                break
            if not events:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/reviews/{task_id}/cancel")
async def cancel_review(task_id: str):
    task = _task_or_404(task_id)
    if task["status"] in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"任务状态为 {task['status']}，无法取消")
    cancelled = await TASK_MANAGER.cancel(task_id)
    if not cancelled:
        raise HTTPException(status_code=409, detail="任务已结束或无法取消")
    return {"task_id": task_id, "status": "cancelled"}


@router.post("/reviews/{task_id}/retry-failed", status_code=202)
async def retry_failed_review(task_id: str):
    task = _task_or_404(task_id)
    if task["status"] not in {"partial_failed", "failed", "interrupted"}:
        raise HTTPException(status_code=409, detail=f"任务状态为 {task['status']}，没有可重试的失败批次")
    try:
        rule_ids = TASK_MANAGER.retry_failed(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"task_id": task_id, "status": "queued", "retry_rule_ids": sorted(rule_ids)}
