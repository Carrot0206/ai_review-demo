from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections import Counter
from typing import Any

from ..executors.ai_executor import group_ai_rules, run_ai_rules
from ..executors.script_executor import execute_rules
from ..models.schemas import (
    BatchLog,
    ExtractedMaterial,
    Issue,
    ReviewResult,
    ReviewSummary,
    RuleBasis,
    RuleExecutionResult,
    RuleSnapshot,
)
from ..storage import database
from .ai_client import AIResponse, DeepSeekClient, get_ai_client, load_ai_config
from .prompts import PROMPT_VERSION
from .rule_library import LibraryProcess, LibraryRule, list_rules


RISK_RANK = {"高风险": 0, "中风险": 1, "低风险": 2}
TERMINAL_STATUSES = {"done", "partial_failed", "failed", "cancelled", "interrupted"}


def create_snapshot(process: LibraryProcess) -> RuleSnapshot:
    rules = [rule for rule in list_rules(process) if rule.enabled]
    if not rules:
        raise ValueError(f"流程 {process} 没有启用规则")
    config_snapshot = load_ai_config(require_key=False).snapshot()
    serialized = json.dumps(
        {
            "process": process,
            "prompt_version": PROMPT_VERSION,
            "model_config": config_snapshot,
            "rules": [rule.model_dump(mode="json") for rule in rules],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return RuleSnapshot(
        snapshot_id=uuid.uuid4().hex,
        process=process,
        sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        prompt_version=PROMPT_VERSION,
        model_config_snapshot=config_snapshot,
        rules=rules,
        created_at=time.time(),
    )


def create_review(process: LibraryProcess, materials: list[ExtractedMaterial]) -> tuple[str, RuleSnapshot]:
    snapshot = create_snapshot(process)
    task_id = uuid.uuid4().hex
    database.create_task(task_id, snapshot, materials)
    database.add_event(
        task_id,
        "task_created",
        {"task_id": task_id, "snapshot_id": snapshot.snapshot_id, "rule_count": len(snapshot.rules)},
    )
    return task_id, snapshot


def _result_issue(rule: LibraryRule, result: RuleExecutionResult, sequence: int) -> Issue:
    basis = RuleBasis(
        basis_type="规则库规则",
        basis_file=rule.basis_text or rule.source_file,
        rule_text=rule.rule_text,
    )
    return Issue(
        issue_id=f"ISSUE-{sequence:04d}",
        rule_id=rule.rule_id,
        review_dimension=rule.review_dimension,
        issue_summary=result.summary or f"{rule.rule_name}未通过审核",
        risk_level=rule.risk_level,
        rule_basis=basis,
        issue_location=result.evidence,
        suggestion=result.suggestion or "请按规则要求核对并修正。",
        execution_method=result.execution_method,
        rule_ids=[rule.rule_id],
        rule_dimensions=[rule.review_dimension],
        rule_bases=[basis],
    )


def _issue_fingerprint(issue: Issue) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted(
            (
                evidence.material_name.strip(),
                reindex_location(evidence.location),
                evidence.value.strip()[:80],
            )
            for evidence in issue.issue_location
        )
    )


def reindex_location(location: str) -> str:
    import re

    return re.sub(r"\[\d+\]", "[]", str(location or "").strip())


def build_issues(rules: list[LibraryRule], results: list[RuleExecutionResult]) -> list[Issue]:
    rule_by_id = {rule.rule_id: rule for rule in rules}
    raw = [
        _result_issue(rule_by_id[result.rule_id], result, sequence)
        for sequence, result in enumerate((item for item in results if item.status == "failed"), start=1)
        if result.rule_id in rule_by_id
    ]
    grouped: dict[tuple[tuple[str, str, str], ...], Issue] = {}
    unlocated: list[Issue] = []
    for issue in raw:
        fingerprint = _issue_fingerprint(issue)
        if not fingerprint:
            unlocated.append(issue)
            continue
        if fingerprint not in grouped:
            grouped[fingerprint] = issue
            continue
        current = grouped[fingerprint]
        current.rule_ids.extend(rule_id for rule_id in issue.rule_ids if rule_id not in current.rule_ids)
        current.rule_dimensions.extend(
            dimension for dimension in issue.rule_dimensions if dimension not in current.rule_dimensions
        )
        current.rule_bases.extend(issue.rule_bases)
        if RISK_RANK.get(issue.risk_level, 9) < RISK_RANK.get(current.risk_level, 9):
            current.risk_level = issue.risk_level
            current.rule_id = issue.rule_id
            current.rule_basis = issue.rule_basis
    issues = list(grouped.values()) + unlocated
    issues.sort(key=lambda item: (RISK_RANK.get(item.risk_level, 9), item.rule_id))
    for sequence, issue in enumerate(issues, start=1):
        issue.issue_id = f"ISSUE-{sequence:04d}"
    return issues


def build_summary(process: LibraryProcess, status: str, results: list[RuleExecutionResult], issues: list[Issue], total_rules: int) -> ReviewSummary:
    counts = Counter(result.status for result in results)
    incomplete = status in {"partial_failed", "failed", "interrupted"} or counts["undetermined"] > 0 or counts["error"] > 0
    conclusion = "审核未完整完成" if incomplete else ("发现审核问题" if issues else "未发现问题")
    return ReviewSummary(
        process=process,
        conclusion=conclusion,
        total_rules=total_rules,
        passed_count=counts["passed"],
        failed_count=counts["failed"],
        not_applicable_count=counts["not_applicable"],
        undetermined_count=counts["undetermined"],
        error_count=counts["error"],
        issue_count=len(issues),
        high_risk_count=sum(issue.risk_level == "高风险" for issue in issues),
        medium_risk_count=sum(issue.risk_level == "中风险" for issue in issues),
        low_risk_count=sum(issue.risk_level == "低风险" for issue in issues),
    )


def get_review_result(task_id: str) -> ReviewResult | None:
    task = database.get_task_row(task_id)
    if not task:
        return None
    snapshot = database.get_snapshot(task["snapshot_id"])
    if not snapshot:
        return None
    results = database.load_rule_results(task_id)
    issues = database.load_issues(task_id)
    batches = database.load_batches(task_id)
    failed_rule_ids = sorted({rule_id for batch in batches if batch.status == "failed" for rule_id in batch.rule_ids})
    return ReviewResult(
        task_id=task_id,
        snapshot_id=snapshot.snapshot_id,
        status=task["status"],
        summary=build_summary(snapshot.process, task["status"], results, issues, len(snapshot.rules)),
        issues=issues,
        rule_results=results,
        batch_logs=batches,
        failed_rule_ids=failed_rule_ids,
    )


class ReviewTaskManager:
    def __init__(self) -> None:
        self.tasks: dict[str, asyncio.Task] = {}
        self.client_override: DeepSeekClient | None = None

    def start(self, task_id: str, retry_rule_ids: set[str] | None = None) -> None:
        if task_id in self.tasks and not self.tasks[task_id].done():
            raise RuntimeError("任务正在运行")
        self.tasks[task_id] = asyncio.create_task(self._run(task_id, retry_rule_ids=retry_rule_ids))

    async def cancel(self, task_id: str) -> bool:
        task_row = database.get_task_row(task_id)
        if not task_row or task_row["status"] in TERMINAL_STATUSES:
            return False
        database.request_cancel(task_id)
        running = self.tasks.get(task_id)
        if running and not running.done():
            running.cancel()
        database.set_task_status(task_id, "cancelled", "用户取消审核")
        database.add_event(task_id, "task_cancelled", {"task_id": task_id})
        return True

    def retry_failed(self, task_id: str) -> set[str]:
        task_row = database.get_task_row(task_id)
        if not task_row:
            raise KeyError(task_id)
        snapshot = database.get_snapshot(task_row["snapshot_id"])
        if not snapshot:
            raise RuntimeError("任务规则快照不存在")
        failed = database.load_failed_batch_rule_ids(task_id)
        existing = {result.rule_id: result for result in database.load_rule_results(task_id)}
        failed.update(rule_id for rule_id, result in existing.items() if result.status == "error")
        failed.update(rule.rule_id for rule in snapshot.rules if rule.rule_id not in existing)
        if not failed:
            raise ValueError("没有可重试的失败规则")
        database.delete_rule_results(task_id, failed)
        database.clear_failed_batches(task_id)
        database.reset_task_for_retry(task_id)
        database.add_event(task_id, "task_retry", {"rule_ids": sorted(failed)})
        self.start(task_id, retry_rule_ids=failed)
        return failed

    async def _batch_callback(
        self,
        task_id: str,
        log: BatchLog,
        results: list[RuleExecutionResult],
        request_payload: dict[str, Any],
        response: AIResponse | None,
    ) -> None:
        database.save_batch(task_id, log, request_payload)
        for result in results:
            database.save_rule_result(task_id, result)
        if response is not None:
            database.save_ai_trace(task_id, log.batch_id, request_payload, response.content, response.parsed)
        database.add_event(
            task_id,
            "batch_update",
            {"batch": log.model_dump(mode="json"), "results": [result.model_dump(mode="json") for result in results]},
        )

    async def _run_ai_safe(
        self,
        *,
        task_id: str,
        process: LibraryProcess,
        rules: list[LibraryRule],
        materials: list[ExtractedMaterial],
        execution_method: str,
        batch_prefix: str,
    ) -> tuple[list[RuleExecutionResult], list[BatchLog], set[str]]:
        if not rules:
            return [], [], set()
        try:
            client = self.client_override or await get_ai_client()
        except Exception as error:
            logs: list[BatchLog] = []
            for index, group in enumerate(group_ai_rules(rules), start=1):
                log = BatchLog(
                    batch_id=f"{batch_prefix}{index:04d}",
                    execution_method=execution_method,
                    review_dimension=group[0].review_dimension,
                    rule_ids=[rule.rule_id for rule in group],
                    status="failed",
                    error=str(error),
                    attempts=0,
                )
                await self._batch_callback(task_id, log, [], {"rule_ids": log.rule_ids}, None)
                logs.append(log)
            return [], logs, {rule.rule_id for rule in rules}
        return await run_ai_rules(
            task_id=task_id,
            process=process,
            rules=rules,
            materials=materials,
            execution_method=execution_method,
            batch_prefix=batch_prefix,
            client=client,
            callback=lambda log, results, request, response: self._batch_callback(
                task_id, log, results, request, response
            ),
        )

    async def _run(self, task_id: str, retry_rule_ids: set[str] | None = None) -> None:
        database.set_task_status(task_id, "running")
        database.add_event(task_id, "task_started", {"retry_rule_ids": sorted(retry_rule_ids or [])})
        task_row = database.get_task_row(task_id)
        if not task_row:
            return
        snapshot = database.get_snapshot(task_row["snapshot_id"])
        materials = database.get_task_materials(task_id)
        if not snapshot:
            database.set_task_status(task_id, "failed", "规则快照不存在")
            return
        try:
            if retry_rule_ids is not None:
                retry_rules = [rule for rule in snapshot.rules if rule.rule_id in retry_rule_ids]
                native_rules = [rule for rule in retry_rules if rule.review_method == "ai"]
                fallback_rules = [rule for rule in retry_rules if rule.review_method == "script"]
                native_outcome, fallback_outcome = await asyncio.gather(
                    self._run_ai_safe(
                        task_id=task_id,
                        process=snapshot.process,
                        rules=native_rules,
                        materials=materials,
                        execution_method="ai",
                        batch_prefix="RTAI-",
                    ),
                    self._run_ai_safe(
                        task_id=task_id,
                        process=snapshot.process,
                        rules=fallback_rules,
                        materials=materials,
                        execution_method="ai_fallback",
                        batch_prefix="RTFB-",
                    ),
                )
                failed_rule_ids = native_outcome[2] | fallback_outcome[2]
            else:
                script_rules = [rule for rule in snapshot.rules if rule.review_method == "script"]
                native_rules = [rule for rule in snapshot.rules if rule.review_method == "ai"]
                native_task = asyncio.create_task(
                    self._run_ai_safe(
                        task_id=task_id,
                        process=snapshot.process,
                        rules=native_rules,
                        materials=materials,
                        execution_method="ai",
                        batch_prefix="AI-",
                    )
                )
                script_results, fallback_rules = await asyncio.to_thread(execute_rules, script_rules, materials)
                for result in script_results:
                    database.save_rule_result(task_id, result)
                database.add_event(
                    task_id,
                    "script_completed",
                    {
                        "result_count": len(script_results),
                        "fallback_rule_ids": [rule.rule_id for rule in fallback_rules],
                    },
                )
                fallback_task = asyncio.create_task(
                    self._run_ai_safe(
                        task_id=task_id,
                        process=snapshot.process,
                        rules=fallback_rules,
                        materials=materials,
                        execution_method="ai_fallback",
                        batch_prefix="FB-",
                    )
                )
                native_outcome, fallback_outcome = await asyncio.gather(native_task, fallback_task)
                failed_rule_ids = native_outcome[2] | fallback_outcome[2]

            if database.is_cancel_requested(task_id):
                database.set_task_status(task_id, "cancelled", "用户取消审核")
                return

            existing = {result.rule_id: result for result in database.load_rule_results(task_id)}
            expected_rules = [
                rule
                for rule in snapshot.rules
                if retry_rule_ids is None or rule.rule_id in retry_rule_ids
            ]
            for rule in expected_rules:
                if rule.rule_id in existing:
                    continue
                database.save_rule_result(
                    task_id,
                    RuleExecutionResult(
                        rule_id=rule.rule_id,
                        status="error",
                        execution_method="ai" if rule.review_method == "ai" else "ai_fallback",
                        error="AI批次执行失败" if rule.rule_id in failed_rule_ids else "规则未产生执行结果",
                    ),
                )

            all_results = database.load_rule_results(task_id)
            issues = build_issues(snapshot.rules, all_results)
            database.replace_issues(task_id, issues)
            status = "partial_failed" if failed_rule_ids else "done"
            database.set_task_status(task_id, status)
            database.add_event(
                task_id,
                "task_finished",
                {"status": status, "issue_count": len(issues), "failed_rule_ids": sorted(failed_rule_ids)},
            )
        except asyncio.CancelledError:
            database.set_task_status(task_id, "cancelled", "用户取消审核")
            raise
        except Exception as error:
            database.set_task_status(task_id, "failed", str(error))
            database.add_event(task_id, "task_failed", {"error": str(error)})


TASK_MANAGER = ReviewTaskManager()

