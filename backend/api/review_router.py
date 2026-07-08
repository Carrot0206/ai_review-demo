"""审核接口：启动任务 + SSE 进度 + 结果查询。"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services.review_service import review
from ..services.rule_sets import load_rule_set_rules, resolve_rule_set_id
from ..services.schemas import BatchLog, Issue, ProcessType
from ..services.upload_store import load_extracted, load_meta
from .jobs import ReviewJob, attach_task, cancel_job, create_job, get_job, push_event, push_progress

router = APIRouter(prefix="/api/review", tags=["review"])


class ReviewStart(BaseModel):
    process: ProcessType
    file_ids: list[str]
    rule_set_id: Optional[str] = None
    include_builtin_rules: bool = True
    max_concurrency: int = 48
    material_slice_enabled: bool = False


async def _run_review_job(job: ReviewJob, payload: ReviewStart):
    if job.cancel_requested:
        return
    job.status = "running"
    try:
        # 1. 加载已解析材料
        materials = []
        for fid in payload.file_ids:
            m = load_extracted(fid)
            if m is None:
                meta = load_meta(fid) or {}
                err = meta.get("parse_error")
                suffix = f"：{err}" if err else ""
                raise RuntimeError(f"文件 {fid} 尚未解析或不存在{suffix}")
            materials.append(m)

        # 2. 上传规则版本（可选；不传时使用当前流程启用版本）
        resolved_rule_set_id = resolve_rule_set_id(payload.process, payload.rule_set_id)
        if payload.rule_set_id and resolved_rule_set_id is None:
            raise RuntimeError(f"规则版本 {payload.rule_set_id} 不存在或不适用于当前流程")
        extra_rules = load_rule_set_rules(resolved_rule_set_id) if resolved_rule_set_id else []

        # 3. 进度回调
        async def cb(msg: str):
            await push_progress(job, msg)

        if resolved_rule_set_id:
            await push_progress(job, f"已加载上传规则版本：{resolved_rule_set_id}（{len(extra_rules)} 条）")
        else:
            await push_progress(job, "未启用上传规则版本，仅使用内置规则")

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
            include_builtin_rules=payload.include_builtin_rules,
        )
        if job.cancel_requested:
            return
        job.result = result
        job.status = "done"
        job.finished_at = time.time()
        await push_progress(job, "__DONE__")
    except asyncio.CancelledError:
        job.cancel_requested = True
        job.status = "cancelled"
        job.error = job.error or "用户已取消审核"
        job.finished_at = time.time()
        return
    except Exception as e:
        if job.cancel_requested:
            job.status = "cancelled"
            job.error = job.error or "用户已取消审核"
            job.finished_at = time.time()
            await push_progress(job, "__CANCELLED__")
            return
        job.status = "failed"
        job.error = str(e)
        job.finished_at = time.time()
        await push_progress(job, f"__FAILED__:{e}")


@router.post("")
async def start_review(payload: ReviewStart):
    if not payload.file_ids:
        raise HTTPException(status_code=400, detail="file_ids 不能为空")
    # 校验文件存在
    for fid in payload.file_ids:
        if load_meta(fid) is None:
            raise HTTPException(status_code=400, detail=f"文件 {fid} 不存在")
        if load_extracted(fid) is None:
            meta = load_meta(fid) or {}
            err = meta.get("parse_error") or "未知解析错误"
            raise HTTPException(status_code=400, detail=f"文件 {fid} 解析失败：{err}")

    job = create_job(payload.process, payload.file_ids)
    attach_task(job, asyncio.create_task(_run_review_job(job, payload)))
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


@router.post("/{job_id}/cancel")
async def cancel_review(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")
    cancelled = await cancel_job(job)
    return {"job_id": job.job_id, "status": job.status, "cancelled": cancelled}


@router.get("/{job_id}/stream")
async def stream_review(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")

    async def event_gen():
        # 把历史消息先发一遍（仅字符串日志；结构化事件不补发，避免重复触发渲染）
        for entry in list(job.progress_log):
            yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
        if job.status == "done":
            yield f"event: done\ndata: {json.dumps({'job_id': job.job_id}, ensure_ascii=False)}\n\n"
            return
        if job.status == "failed":
            yield f"event: failed\ndata: {json.dumps({'error': job.error or 'failed'}, ensure_ascii=False)}\n\n"
            return
        if job.status == "cancelled":
            yield f"event: cancelled\ndata: {json.dumps({'job_id': job.job_id}, ensure_ascii=False)}\n\n"
            return
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
            if msg == "__CANCELLED__":
                yield f"event: cancelled\ndata: {json.dumps({'job_id': job.job_id}, ensure_ascii=False)}\n\n"
                break
            if msg.startswith("__FAILED__"):
                yield f"event: failed\ndata: {json.dumps({'error': msg[len('__FAILED__:'):]}, ensure_ascii=False)}\n\n"
                break
            yield f"data: {json.dumps({'msg': msg}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
