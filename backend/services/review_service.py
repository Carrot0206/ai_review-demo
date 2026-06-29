"""核心审核服务：组合规则加载 + 材料解析 + LLM 调用，产出 ReviewResult。"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Iterable, Optional, Union

from .llm_client import DeepSeekClient
from .material_filter import filter_materials, materials_needed_by_group
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
# O6：每完成一批立即回调，把这批的 issues + log 推送给上层（用于 SSE 流式渲染）
BatchDoneCallback = Callable[[list["Issue"], "BatchLog"], Union[Awaitable[None], None]]


async def _emit(progress_cb: Optional[ProgressCallback], msg: str) -> None:
    if progress_cb is None:
        return
    res = progress_cb(msg)
    if asyncio.iscoroutine(res):
        await res


async def _emit_batch_done(
    cb: Optional[BatchDoneCallback], issues: list, log
) -> None:
    if cb is None:
        return
    res = cb(issues, log)
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
        review_dimension=rule.review_dimension,
        issue_summary=str(raw.get("issue_summary", "") or "").strip(),
        risk_level=rule.risk_level,  # 后端回填
        rule_basis=RuleBasis(
            basis_type="用户新增规则" if rule_id.startswith("USER-") else "内置规则",
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
        # O1：按本批规则的 applicable_materials 裁剪材料
        needed = materials_needed_by_group(group)
        filtered_materials = filter_materials(materials, needed)
        materials_used = [m.material_name for m in filtered_materials]
        messages = build_messages(process, group, materials, material_filter=needed)
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
            materials_used=materials_used,
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


def _leaf_field(loc: IssueLocation) -> str:
    """提取 location 最末段字段名，忽略页码/数字序号/逗号/空白等噪声。

    用于"事实级"聚类——把 "第1页, 产品基本信息.信托产品全称"、
    "1.产品基本信息.信托产品全称"、"产品基本信息.信托产品全称"
    都归一到 leaf="信托产品全称"。
    """
    import re

    raw = (loc.location or "").strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1].strip()
    raw = re.sub(r"\[\d+\]", "", raw)
    # 由 .,， 、 空格 分隔
    parts = re.split(r"[.,，、\s]+", raw)
    cleaned: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if re.fullmatch(r"\d+", p):
            continue
        if re.fullmatch(r"第\d+[页段章节]", p):
            continue
        cleaned.append(p)
    return cleaned[-1] if cleaned else ""


def _defect_pairs(issue: Issue) -> frozenset:
    """事实级缺陷指纹：忽略 value、路径噪声后的 {(material, leaf_field)} 集合。

    用于跨规则去重——两条 issue 若指向完全相同的 (material, leaf_field) 集合，
    或一个是另一个的子集（leaf 集合一致），视作同一事实错误。

    特殊：当 loc.value 以 "缺失:" 开头时（约定的缺失字段占位），
    用 ("__MISSING__", <target>) 替代正常的 (material, leaf) pair。
    这样同一缺失目标（例如 "缺失:信托文件样本"）由不同材料报出时也能归一聚合。
    """
    if not issue.issue_location:
        return frozenset()
    pairs: set[tuple[str, str]] = set()
    for loc in issue.issue_location:
        value = (loc.value or "").strip()
        if value.startswith("缺失:") or value.startswith("缺失："):
            # 取冒号后的目标
            target = value.split(":", 1)[-1] if ":" in value else value.split("：", 1)[-1]
            target = target.strip()
            if target:
                pairs.add(("__MISSING__", target))
                continue
        pairs.add(((loc.material_name or "").strip(), _leaf_field(loc)))
    # 丢掉 leaf 抽不出的（避免空 leaf 误聚）
    return frozenset(p for p in pairs if p[1])


# 通用的"缺失/未填写"占位符。仍保留——_location_fingerprint / 其它老路径可能用到。
GENERIC_MISSING_VALUES = {
    "",
    "缺失",
    "字段缺失",
    "未填写",
    "未填",
    "空",
    "无",
    "null",
    "None",
    "N/A",
    "n/a",
    "NA",
}


def _is_coarse_location(loc: IssueLocation) -> bool:
    """location 是否粗粒度（≤1 段路径），或 value 是通用缺失占位符。"""
    import re

    path = (loc.location or "").strip()
    if path.startswith("[") and path.endswith("]"):
        path = path[1:-1].strip()
    path = re.sub(r"\[\d+\]", "", path)
    parts = [p for p in path.split(".") if p]
    coarse = len(parts) <= 1

    value = (loc.value or "").strip()
    generic_value = value in GENERIC_MISSING_VALUES

    return coarse or generic_value


def _merge_issues(issues: list[Issue]) -> list[Issue]:
    """聚类合并：同一事实错误的多条 Issue 合并为一条。

    新的两遍聚类策略（彻底忽略 value 和路径噪声）：

    1) 一遍按精确 _defect_pairs（material × leaf_field 的有序集合）聚类——
       命中同一组 (material, 字段) 的不同规则会被合并。
       这能解决：同一缺陷的不同表述（"缺失:X" / "（空）" / 旧值）、
       同一字段被不同路径前缀报告（"第1页, 产品基本信息.X" 与 "产品基本信息.X"）。

    2) 二遍 subsumption——若 cluster A 的 pairs 是 cluster B 的真子集且
       leaf_field 集合相同，把 A 并入 B。
       这能解决：#3（仅模板字段缺失）与 #8（申请书与模板不一致，模板侧也缺失）
       本质指向同一字段缺陷，应合并。

    合并时取 location 覆盖最全的那条作为代表 location；rule_ids/rule_bases/
    alt_summaries/alt_suggestions 累积其余条目；risk_level 取最高。
    """
    risk_rank = {"高风险": 0, "中风险": 1, "低风险": 2}

    # 第一遍：按 defect_pairs 精确聚类
    initial_clusters: dict = {}
    order_keys: list = []
    no_loc_issues: list[Issue] = []
    for it in issues:
        pairs = _defect_pairs(it)
        if not pairs:
            no_loc_issues.append(it)
            continue
        if pairs not in initial_clusters:
            initial_clusters[pairs] = []
            order_keys.append(pairs)
        initial_clusters[pairs].append(it)

    # 第二遍：subsumption — small ⊂ big 且 leaf 集合一致 → small 并入 big
    keys = list(initial_clusters.keys())
    parent: dict = {k: k for k in keys}
    keys_by_size = sorted(keys, key=lambda s: len(s))  # 小到大
    for small in keys_by_size:
        small_leaves = {leaf for _, leaf in small}
        if not small_leaves:
            continue
        best_big = None
        best_size = -1
        for big in keys:
            if big == small:
                continue
            if small < big:  # 真子集
                big_leaves = {leaf for _, leaf in big}
                # 放宽：small.leaves ⊆ big.leaves 即可（不再要求完全相等）
                # pairs ⊂ 已是强约束，足以避免误并；
                # 允许 big 含 small 没有的额外 leaf（如同字段不同路径表述）。
                if small_leaves <= big_leaves and len(big) > best_size:
                    best_big = big
                    best_size = len(big)
        if best_big is not None:
            parent[small] = best_big

    def _resolve(k):
        cur = k
        while parent[cur] != cur:
            cur = parent[cur]
        return cur

    final_clusters: dict = {}
    final_order: list = []
    for k in order_keys:
        tgt = _resolve(k)
        if tgt not in final_clusters:
            final_clusters[tgt] = []
            final_order.append(tgt)
        final_clusters[tgt].extend(initial_clusters[k])

    # 无 location 的 issue 走 summary 兜底
    no_loc_map: dict = {}
    for it in no_loc_issues:
        k = f"NOLOC||{(it.issue_summary or '')[:24]}"
        if k not in no_loc_map:
            no_loc_map[k] = []
            final_order.append(k)
        no_loc_map[k].append(it)
    final_clusters.update(no_loc_map)

    merged: list[Issue] = []
    for key in final_order:
        group = final_clusters[key]
        # 主条目：风险最高 + 风险相同时 location 覆盖最全
        group.sort(
            key=lambda x: (
                risk_rank.get(x.risk_level, 9),
                -len(_defect_pairs(x)),
                -len(x.issue_location),
            )
        )
        head = group[0]

        # 取 location 覆盖最全的那条作为代表 location（信息最丰富）
        best_locations = head.issue_location
        best_pairs_size = len(_defect_pairs(head))
        for other in group[1:]:
            other_size = len(_defect_pairs(other))
            if other_size > best_pairs_size:
                best_locations = other.issue_location
                best_pairs_size = other_size

        rule_ids = [head.rule_id]
        rule_dimensions = [head.review_dimension]
        rule_bases = [head.rule_basis]
        alt_summaries: list[str] = []
        alt_suggestions: list[str] = []

        for other in group[1:]:
            if other.rule_id not in rule_ids:
                rule_ids.append(other.rule_id)
                rule_dimensions.append(other.review_dimension)
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
                review_dimension=head.review_dimension,
                issue_summary=head.issue_summary,
                risk_level=head.risk_level,
                rule_basis=head.rule_basis,
                issue_location=best_locations,
                suggestion=head.suggestion,
                rule_ids=rule_ids,
                rule_dimensions=rule_dimensions,
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
    on_batch_done: Optional[BatchDoneCallback] = None,
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
            issues, log = await _run_batch(
                client, process, group, materials, rules_by_id, batch_id, progress_cb
            )
            # O6：批次完成立即推送（流式渲染）
            await _emit_batch_done(on_batch_done, issues, log)
            return issues, log

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
