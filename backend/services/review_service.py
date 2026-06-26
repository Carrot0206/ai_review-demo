"""核心审核服务：组合规则加载 + 材料解析 + LLM 调用，产出 ReviewResult。"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Iterable, Optional, Union

from .llm_client import DeepSeekClient
from .material_parser import parse_material
from .prompt_builder import build_messages
from .rule_loader import (
    describe_group,
    group_by_dimension,
    load_rules,
    split_for_ai_and_human,
)
from .schemas import (
    BatchLog,
    ExtractedMaterial,
    HumanReviewItem,
    Issue,
    IssueLocation,
    PROCESS_LABEL,
    ProcessType,
    ReviewResult,
    ReviewSummary,
    Rule,
    RuleBasis,
)


ProgressCallback = Callable[[str], Union[Awaitable[None], None]]


async def _emit(progress_cb: Optional[ProgressCallback], msg: str) -> None:
    if progress_cb is None:
        return
    res = progress_cb(msg)
    if asyncio.iscoroutine(res):
        await res


def _build_issue_from_model(raw: dict, rules_by_id: dict, ) -> Optional[Issue]:
    """把模型返回的一个 issue 字典套用本地规则回填 → Issue。"""
    rule_id = (raw.get("rule_id") or "").strip()
    rule = rules_by_id.get(rule_id)
    if rule is None:
        # 模型返回了不在本批次的 rule_id，丢弃，避免幻觉污染结果
        return None

    locations_raw = raw.get("issue_location") or []
    locations: list[IssueLocation] = []
    for loc in locations_raw:
        if not isinstance(loc, dict):
            continue
        locations.append(
            IssueLocation(
                material_name=str(loc.get("material_name", "") or ""),
                location=str(loc.get("location", "") or ""),
                value=str(loc.get("value", "") or ""),
            )
        )

    return Issue(
        issue_id="",  # 在合并阶段统一编号
        rule_id=rule_id,
        issue_summary=str(raw.get("issue_summary", "") or "").strip(),
        risk_level=rule.risk_level,  # 后端回填
        rule_basis=RuleBasis(
            basis_type="内置规则",
            basis_file=rule.basis_file or "",
            rule_text=rule.rule_text or "",
        ),
        issue_location=locations,
        suggestion=str(raw.get("suggestion", "") or "").strip(),
    )


async def _run_batch(
    client: DeepSeekClient,
    process: ProcessType,
    group,
    materials,
    rules_by_id,
    batch_id: str,
    progress_cb: Optional[ProgressCallback],
):
    start = time.perf_counter()
    label = describe_group(group)
    await _emit(progress_cb, f"[{batch_id}] 开始审核 {label}")
    try:
        messages = build_messages(process, group, materials)
        resp = await client.chat(messages)
        raw_issues = resp.parsed.get("issues") or []
        issues: list[Issue] = []
        for raw in raw_issues:
            if isinstance(raw, dict):
                built = _build_issue_from_model(raw, rules_by_id)
                if built is not None:
                    issues.append(built)
        duration = time.perf_counter() - start
        log = BatchLog(
            batch_id=batch_id,
            review_dimension=label,
            rule_count=len(group),
            status="success",
            issues_found=len(issues),
            duration_seconds=round(duration, 2),
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
        )
        await _emit(
            progress_cb,
            f"[{batch_id}] 完成 {label}：{len(issues)} 个问题，"
            f"耗时 {log.duration_seconds}s，tokens in/out={log.input_tokens}/{log.output_tokens}",
        )
        return issues, log
    except Exception as e:
        duration = time.perf_counter() - start
        log = BatchLog(
            batch_id=batch_id,
            review_dimension=label,
            rule_count=len(group),
            status="failed",
            duration_seconds=round(duration, 2),
            error=str(e),
        )
        await _emit(progress_cb, f"[{batch_id}] 失败 {label}：{e}")
        return [], log


def _summarize(process: ProcessType, issues: Iterable[Issue]) -> ReviewSummary:
    items = list(issues)
    summary = ReviewSummary(
        registration_type=PROCESS_LABEL.get(process, process),
        total_issues=len(items),
    )
    for it in items:
        if it.risk_level == "高风险":
            summary.high_risk_count += 1
        elif it.risk_level == "中风险":
            summary.medium_risk_count += 1
        elif it.risk_level == "低风险":
            summary.low_risk_count += 1
    return summary


def _location_fingerprint(loc: IssueLocation) -> str:
    """把单个 location 归一为指纹，用于聚类。

    归一规则：
    - 去掉 "[0]" 这类下标
    - 去掉首尾包裹的方括号
    - 路径只取末尾两段（如 "信托产品事前报告模板.产品基本信息.信托产品全称" 与
      "产品基本信息.信托产品全称" 均归一为 "产品基本信息.信托产品全称"）
    - value 取前 24 字
    """
    import re

    material = (loc.material_name or "").strip()

    path = (loc.location or "").strip()
    # 去掉首尾方括号
    if path.startswith("[") and path.endswith("]"):
        path = path[1:-1].strip()
    # 去掉数组下标
    path = re.sub(r"\[\d+\]", "", path)
    # 取末尾两段
    parts = [p for p in path.split(".") if p]
    tail = ".".join(parts[-2:]) if parts else ""

    value = (loc.value or "").strip()[:24]
    return f"{material}||{tail}||{value}"


def _issue_cluster_key(issue: Issue) -> str:
    """整个 Issue 的聚类 key：把所有 location 指纹排序拼接。"""
    if not issue.issue_location:
        return f"NOLOC||{issue.issue_summary[:24]}"
    fps = sorted(_location_fingerprint(l) for l in issue.issue_location)
    # 仅按 location 指纹合并，不考虑 risk_level
    # 不同规则发现同一事实时 risk_level 应一致（由后端按规则回填，几乎不冲突）
    return " | ".join(fps)


def _merge_issues(issues: list[Issue]) -> list[Issue]:
    """聚类合并：相同 location 指纹的多条 Issue 合成一条。

    保留首条作为主条目；rule_ids/rule_bases/alt_summaries/alt_suggestions 追加其余条目内容。
    若 risk_level 不一致，按"取最高"原则（高>中>低）。
    """
    risk_rank = {"高风险": 0, "中风险": 1, "低风险": 2}
    clusters: dict[str, list[Issue]] = {}
    order: list[str] = []
    for it in issues:
        key = _issue_cluster_key(it)
        if key not in clusters:
            clusters[key] = []
            order.append(key)
        clusters[key].append(it)

    merged: list[Issue] = []
    for key in order:
        group = clusters[key]
        # 按风险等级排序：把最高风险的放在第 0 位作为主条目
        group.sort(key=lambda x: risk_rank.get(x.risk_level, 9))
        head = group[0]

        rule_ids = [head.rule_id]
        rule_bases = [head.rule_basis]
        alt_summaries: list[str] = []
        alt_suggestions: list[str] = []

        for other in group[1:]:
            if other.rule_id not in rule_ids:
                rule_ids.append(other.rule_id)
                rule_bases.append(other.rule_basis)
            if other.issue_summary and other.issue_summary != head.issue_summary:
                if other.issue_summary not in alt_summaries:
                    alt_summaries.append(other.issue_summary)
            if other.suggestion and other.suggestion != head.suggestion:
                if other.suggestion not in alt_suggestions:
                    alt_suggestions.append(other.suggestion)

        merged.append(
            Issue(
                issue_id=head.issue_id,
                rule_id=head.rule_id,
                issue_summary=head.issue_summary,
                risk_level=head.risk_level,
                rule_basis=head.rule_basis,
                issue_location=head.issue_location,
                suggestion=head.suggestion,
                rule_ids=rule_ids,
                rule_bases=rule_bases,
                alt_summaries=alt_summaries,
                alt_suggestions=alt_suggestions,
            )
        )
    return merged


async def review(
    process: ProcessType,
    material_paths=None,
    *,
    materials_preloaded: Optional[list] = None,
    extra_rules: Optional[list] = None,
    client: Optional[DeepSeekClient] = None,
    max_concurrency: int = 4,
    progress_cb: Optional[ProgressCallback] = None,
    rule_id_whitelist: Optional[set] = None,
) -> ReviewResult:
    """主流程：加载规则→解析材料→分批并发调 LLM→合并结果。

    参数：
      material_paths: 需要在此函数内现解析的材料路径
      materials_preloaded: 已解析的 ExtractedMaterial 列表（直接复用，例如上传缓存）
      extra_rules: 额外混入的规则（例如用户新增规则）
    """
    # 1. 规则
    all_rules = load_rules(process)
    if extra_rules:
        all_rules.extend(extra_rules)
    if rule_id_whitelist:
        all_rules = [r for r in all_rules if r.rule_id in rule_id_whitelist]
    ai_rules, human_rules = split_for_ai_and_human(all_rules)
    await _emit(
        progress_cb,
        f"加载规则完成：AI 审核 {len(ai_rules)} 条，需人工复核 {len(human_rules)} 条",
    )

    # 2. 材料
    materials: list[ExtractedMaterial] = []
    if materials_preloaded:
        materials.extend(materials_preloaded)
        for m in materials_preloaded:
            await _emit(
                progress_cb,
                f"已加载预解析材料：{m.material_name}（{len(m.segments)} 个片段）",
            )
    for p in material_paths or []:
        m = parse_material(p)
        materials.append(m)
        await _emit(progress_cb, f"已解析材料：{m.material_name}（{len(m.segments)} 个片段）")

    if not ai_rules:
        await _emit(progress_cb, "AI 审核规则为空，跳过 LLM 调用")
        result = ReviewResult(
            summary=_summarize(process, []),
            issues=[],
            human_review_items=[
                HumanReviewItem(
                    rule_id=r.rule_id,
                    rule_name=r.rule_name,
                    rule_text=r.rule_text,
                    reason=f"check_type={r.check_type}，属于版式/显著位置类，AI 不可靠",
                )
                for r in human_rules
            ],
            batch_logs=[],
        )
        return result

    # 3. 分组 & 并发
    groups = group_by_dimension(ai_rules)
    rules_by_id = {r.rule_id: r for r in ai_rules}
    await _emit(progress_cb, f"分组完成：共 {len(groups)} 批")

    client = client or DeepSeekClient()
    sem = asyncio.Semaphore(max(1, max_concurrency))

    async def worker(idx: int, group: list[Rule]):
        async with sem:
            batch_id = f"B{idx+1:02d}"
            return await _run_batch(
                client, process, group, materials, rules_by_id, batch_id, progress_cb
            )

    batch_results = await asyncio.gather(*[worker(i, g) for i, g in enumerate(groups)])

    # 4. 合并结果
    all_issues: list[Issue] = []
    batch_logs: list[BatchLog] = []
    for issues, log in batch_results:
        all_issues.extend(issues)
        batch_logs.append(log)

    # 4.1 同一事实错误合并：按 issue_location 指纹聚类
    raw_count = len(all_issues)
    all_issues = _merge_issues(all_issues)
    if raw_count != len(all_issues):
        await _emit(
            progress_cb,
            f"问题合并：{raw_count} → {len(all_issues)}（同一事实错误的多条规则命中已合并）",
        )

    # 5. 编号 + 排序（高→中→低，规则内按 rule_id 稳定排序）
    risk_order = {"高风险": 0, "中风险": 1, "低风险": 2}
    all_issues.sort(key=lambda x: (risk_order.get(x.risk_level, 9), x.rule_id))
    for i, it in enumerate(all_issues, start=1):
        it.issue_id = f"ISSUE-{i:03d}"

    human_items = [
        HumanReviewItem(
            rule_id=r.rule_id,
            rule_name=r.rule_name,
            rule_text=r.rule_text,
            reason=f"check_type={r.check_type}，属于版式/显著位置类，AI 不可靠",
        )
        for r in human_rules
    ]

    return ReviewResult(
        summary=_summarize(process, all_issues),
        issues=all_issues,
        human_review_items=human_items,
        batch_logs=batch_logs,
    )
