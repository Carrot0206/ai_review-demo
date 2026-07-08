"""审核任务在内存中的状态管理 + SSE 推送队列。"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from ..services.schemas import ReviewResult


@dataclass
class ReviewJob:
    job_id: str
    process: str
    file_ids: list = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    status: str = "pending"  # pending / running / done / failed / cancelled
    result: Optional[ReviewResult] = None
    error: Optional[str] = None
    task: Optional[asyncio.Task] = None
    cancel_requested: bool = False
    # 进度消息日志
    progress_log: list = field(default_factory=list)
    # 给 SSE 用的异步队列；元素可以是 str（兼容历史）或 dict（结构化事件）
    queue: "asyncio.Queue[Union[str, dict]]" = field(default_factory=asyncio.Queue)


_JOBS: dict[str, ReviewJob] = {}


def create_job(process: str, file_ids: list) -> ReviewJob:
    job_id = uuid.uuid4().hex[:12]
    job = ReviewJob(
        job_id=job_id,
        process=process,
        file_ids=list(file_ids),
        started_at=time.time(),
        status="pending",
    )
    _JOBS[job_id] = job
    return job


def attach_task(job: ReviewJob, task: asyncio.Task) -> None:
    job.task = task


def get_job(job_id: str) -> Optional[ReviewJob]:
    return _JOBS.get(job_id)


def list_jobs() -> list[ReviewJob]:
    return list(_JOBS.values())


async def push_progress(job: ReviewJob, msg: str) -> None:
    job.progress_log.append({"ts": time.time(), "msg": msg})
    await job.queue.put(msg)


async def push_event(job: ReviewJob, event: str, data: Any) -> None:
    """推送结构化 SSE 事件（example: batch_done / batch_failed）。"""
    await job.queue.put({"event": event, "data": data})


async def cancel_job(job: ReviewJob, reason: str = "用户已取消审核") -> bool:
    if job.status in {"done", "failed", "cancelled"}:
        return False
    job.cancel_requested = True
    job.status = "cancelled"
    job.finished_at = time.time()
    job.error = reason
    job.progress_log.append({"ts": time.time(), "msg": reason})
    await job.queue.put("__CANCELLED__")
    if job.task and not job.task.done():
        job.task.cancel()
    return True
