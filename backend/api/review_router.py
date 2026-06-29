"""审核接口：启动任务 + SSE 进度 + 结果查询。"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services.review_service import review
from ..services.schemas import BatchLog, Issue, ProcessType
from ..services.upload_store import load_extracted, load_meta
from ..services.user_rules import list_user_rules, to_review_rule
from .jobs import ReviewJob, create_job, get_job, push_event, push_progress

router = APIRouter(prefix="/api/review", tags=["review"])


class ReviewStart(BaseModel):
    process: ProcessType
    file_ids: list[str]
    user_rule_ids: Optional[list[str]] = None  # None = 用全部已启用的用户规则；空列表 = 不用
    max_concurrency: int = 4
    material_slice_enabled: bool = False


async def _run_review_job(job: ReviewJob, payload: ReviewStart):
    job.status = "running"
    try:
        # 1. 加载已解析材料
        materials = []
        for fid in payload.file_ids:
            m = load_extracted(fid)
            if m is None:
                raise RuntimeError(f"文件 {fid} 尚未解析或不存在")
            materials.append(m)

        # 2. 用户新增规则
        all_user_rules = list_user_rules(payload.process)
        if payload.user_rule_ids is None:
            chosen = all_user_rules
        else:
            chosen_set = set(payload.user_rule_ids)
            chosen = [r for r in all_user_rules if r.rule_id in chosen_set]
        extra_rules = [to_review_rule(ur) for ur in chosen if ur.enabled]

        # 3. 进度回调
        async def cb(msg: str):
            await push_progress(job, msg)

        # 3.1 每批完成回调（O6：流式推送）
        async def batch_cb(issues: list[Issue], log: BatchLog):
            await push_event(
                job,
                "batch_done",
                {
                    "batch": log.model_dump(),
                    "issues": [i.model_dump() for i in issues],
                },
            )

        # 4. 跑！
        result = await review(
            process=payload.process,
            materials_preloaded=materials,
            extra_rules=extra_rules,
            max_concurrency=payload.max_concurrency,
            progress_cb=cb,
            on_batch_done=batch_cb,
            material_slice_enabled=payload.material_slice_enabled,
        )
        job.result = result
        job.status = "done"
        await push_progress(job, "__DONE__")
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        await push_progress(job, f"__FAILED__:{e}")


@router.post("")
async def start_review(payload: ReviewStart):
    if not payload.file_ids:
        raise HTTPException(status_code=400, detail="file_ids 不能为空")
    # 校验文件存在
    for fid in payload.file_ids:
        if load_meta(fid) is None:
            raise HTTPException(status_code=400, detail=f"文件 {fid} 不存在")

    job = create_job(payload.process, payload.file_ids)
    asyncio.create_task(_run_review_job(job, payload))
    return {"job_id": job.job_id, "status": job.status}


@router.get("/{job_id}")
def get_review(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")
    return {
        "job_id": job.job_id,
        "process": job.process,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "result": job.result.model_dump() if job.result else None,
        "progress_log": job.progress_log,
    }


@router.get("/{job_id}/stream")
async def stream_review(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")

    async def event_gen():
        # 把历史消息先发一遍（仅字符串日志；结构化事件不补发，避免重复触发渲染）
        for entry in list(job.progress_log):
            yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
        # 持续监听
        while True:
            try:
                msg = await asyncio.wait_for(job.queue.get(), timeout=60.0)
            except asyncio.TimeoutError:
                # 心跳，避免代理断开
                yield ": keep-alive\n\n"
                continue
            # 结构化事件（dict）
            if isinstance(msg, dict):
                event_name = msg.get("event") or "message"
                data = msg.get("data") or {}
                yield f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                continue
            # 字符串日志（兼容历史）
            if msg == "__DONE__":
                yield f"event: done\ndata: {json.dumps({'job_id': job.job_id}, ensure_ascii=False)}\n\n"
                break
            if msg.startswith("__FAILED__"):
                yield f"event: failed\ndata: {json.dumps({'error': msg[len('__FAILED__:'):]}, ensure_ascii=False)}\n\n"
                break
            yield f"data: {json.dumps({'msg': msg}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
