from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Optional

from ..models.schemas import BatchLog, ExtractedMaterial, RuleEvidence, RuleExecutionResult
from ..services.ai_client import AIResponse, DeepSeekClient, load_ai_config
from ..services.material_context import select_material_context
from ..services.prompts import build_messages
from ..services.rule_library import LibraryProcess, LibraryRule


BATCH_SIZE = 4
_GLOBAL_SEMAPHORE = asyncio.Semaphore(max(1, load_ai_config(require_key=False).max_concurrency))
BatchCallback = Callable[
    [BatchLog, list[RuleExecutionResult], dict[str, Any], Optional[AIResponse]],
    Awaitable[None],
]


def group_ai_rules(rules: list[LibraryRule]) -> list[list[LibraryRule]]:
    buckets: dict[tuple[str, tuple[str, ...]], list[LibraryRule]] = defaultdict(list)
    for rule in rules:
        key = (rule.review_dimension, tuple(sorted(rule.applicable_materials)))
        buckets[key].append(rule)
    groups: list[list[LibraryRule]] = []
    for key in sorted(buckets, key=lambda item: (item[0], item[1])):
        items = sorted(buckets[key], key=lambda rule: rule.rule_id)
        groups.extend(items[index : index + BATCH_SIZE] for index in range(0, len(items), BATCH_SIZE))
    return groups


def _validate_results(
    rules: list[LibraryRule],
    parsed: dict[str, Any],
    execution_method: Literal["ai", "ai_fallback"],
    batch_id: str,
) -> list[RuleExecutionResult]:
    raw_results = parsed.get("results")
    if not isinstance(raw_results, list):
        raise ValueError("AI响应缺少results数组")
    expected_ids = {rule.rule_id for rule in rules}
    returned_ids = [str(item.get("rule_id") or "") for item in raw_results if isinstance(item, dict)]
    if len(returned_ids) != len(set(returned_ids)):
        raise ValueError("AI响应包含重复rule_id")
    if set(returned_ids) != expected_ids:
        raise ValueError(f"AI响应rule_id集合不匹配：expected={sorted(expected_ids)}, actual={sorted(returned_ids)}")
    allowed_statuses = {"passed", "failed", "not_applicable", "undetermined"}
    results: list[RuleExecutionResult] = []
    for item in raw_results:
        status = str(item.get("status") or "")
        if status not in allowed_statuses:
            raise ValueError(f"AI响应状态非法：{status}")
        evidence = [
            RuleEvidence.model_validate(value)
            for value in item.get("evidence") or []
            if isinstance(value, dict)
        ]
        if status == "failed" and not str(item.get("summary") or "").strip():
            raise ValueError("failed结果必须包含summary")
        results.append(
            RuleExecutionResult(
                rule_id=str(item["rule_id"]),
                status=status,
                execution_method=execution_method,
                summary=str(item.get("summary") or "").strip(),
                suggestion=str(item.get("suggestion") or "").strip(),
                evidence=evidence,
                batch_id=batch_id,
            )
        )
    return results


async def _run_group(
    *,
    task_id: str,
    process: LibraryProcess,
    rules: list[LibraryRule],
    materials: list[ExtractedMaterial],
    execution_method: Literal["ai", "ai_fallback"],
    batch_id: str,
    client: DeepSeekClient,
    callback: BatchCallback | None,
) -> tuple[list[RuleExecutionResult], BatchLog]:
    selected_materials, materials_used, slice_fallback = select_material_context(rules, materials)
    messages = build_messages(process, rules[0].review_dimension, rules, selected_materials, execution_method)
    request_payload = {
        "task_id": task_id,
        "batch_id": batch_id,
        "rule_ids": [rule.rule_id for rule in rules],
        "messages": messages,
        "slice_fallback": slice_fallback,
    }
    started = time.perf_counter()
    running_log = BatchLog(
        batch_id=batch_id,
        execution_method=execution_method,
        review_dimension=rules[0].review_dimension,
        rule_ids=[rule.rule_id for rule in rules],
        status="running",
        materials_used=materials_used,
    )
    if callback:
        await callback(running_log, [], request_payload, None)
    last_error: Exception | None = None
    response: AIResponse | None = None
    attempts = 0
    for attempt in range(client.config.max_retries + 1):
        attempts = attempt + 1
        try:
            async with _GLOBAL_SEMAPHORE:
                response = await client.chat(messages)
            results = _validate_results(rules, response.parsed, execution_method, batch_id)
            duration = round(time.perf_counter() - started, 3)
            for result in results:
                result.duration_seconds = duration
            log = running_log.model_copy(
                update={
                    "status": "success",
                    "duration_seconds": duration,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "attempts": attempts,
                }
            )
            if callback:
                await callback(log, results, request_payload, response)
            return results, log
        except Exception as error:
            last_error = error
            if attempt < client.config.max_retries:
                await asyncio.sleep(1.5 * (2**attempt))
    log = running_log.model_copy(
        update={
            "status": "failed",
            "duration_seconds": round(time.perf_counter() - started, 3),
            "error": str(last_error or "AI批次失败"),
            "attempts": attempts,
        }
    )
    if callback:
        await callback(log, [], request_payload, response)
    return [], log


async def run_ai_rules(
    *,
    task_id: str,
    process: LibraryProcess,
    rules: list[LibraryRule],
    materials: list[ExtractedMaterial],
    execution_method: Literal["ai", "ai_fallback"],
    batch_prefix: str,
    client: DeepSeekClient,
    callback: BatchCallback | None = None,
) -> tuple[list[RuleExecutionResult], list[BatchLog], set[str]]:
    groups = group_ai_rules(rules)
    tasks = [
        _run_group(
            task_id=task_id,
            process=process,
            rules=group,
            materials=materials,
            execution_method=execution_method,
            batch_id=f"{batch_prefix}{index + 1:04d}",
            client=client,
            callback=callback,
        )
        for index, group in enumerate(groups)
    ]
    if not tasks:
        return [], [], set()
    outcomes = await asyncio.gather(*tasks)
    results = [result for batch_results, _ in outcomes for result in batch_results]
    logs = [log for _, log in outcomes]
    failed_rule_ids = {rule_id for log in logs if log.status == "failed" for rule_id in log.rule_ids}
    return results, logs, failed_rule_ids
