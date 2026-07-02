"""核心审核服务：组合规则加载 + 材料解析 + LLM 调用，产出 ReviewResult。"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Iterable, Optional, Union

from .llm_client import DeepSeekClient
from .material_filter import filter_materials, materials_needed_by_group
from .material_parser import parse_material
from .material_slicer import slice_materials_for_group
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


def _display_location(raw: str) -> str:
    """Convert JSON array paths to one-based business-facing paths.

    The parser keeps array indexes internally (for example
    "初始受益权信息[0].受益凭据编号"). Review output keeps the record marker,
    but uses one-based indexes: "[0]" -> "[1]", "[1]" -> "[2]".
    """
    import re

    def repl(match: re.Match) -> str:
        return f"[{int(match.group(1)) + 1}]"

    return re.sub(r"\[(\d+)\]", repl, str(raw or ""))


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
                location=_display_location(str(loc.get("location", "") or "")),
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
        severity_type=rule.severity_type,
        issue_type=rule.issue_type,
    )


async def _run_batch(
    client: DeepSeekClient,
    process: ProcessType,
    group,
    materials,
    rules_by_id,
    batch_id: str,
    progress_cb: Optional[ProgressCallback],
    material_slice_enabled: bool = False,
):
    start = time.perf_counter()
    label = describe_group(group)
    await _emit(progress_cb, f"[{batch_id}] 开始审核 {label}")
    try:
        # O1：按本批规则的 applicable_materials 裁剪材料
        needed = materials_needed_by_group(group)
        filtered_materials = filter_materials(materials, needed)
        slice_result = slice_materials_for_group(
            group,
            filtered_materials,
            enabled=material_slice_enabled,
        )
        prompt_materials = slice_result.materials
        materials_used = [m.material_name for m in prompt_materials]
        if material_slice_enabled:
            await _emit(progress_cb, f"[{batch_id}] {slice_result.summary}")
        messages = build_messages(process, group, prompt_materials)
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
            slice_enabled=slice_result.enabled,
            slice_summary=slice_result.summary,
            original_segment_count=slice_result.original_segment_count,
            sliced_segment_count=slice_result.sliced_segment_count,
            slice_fallback=slice_result.fallback,
            slice_confidence=slice_result.confidence,
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
    issue_items = [it for it in items if it.severity_type != "risk_hint"]
    summary = ReviewSummary(
        registration_type=PROCESS_LABEL.get(process, process),
        total_issues=len(issue_items),
        risk_hint_count=sum(1 for it in items if it.severity_type == "risk_hint"),
    )
    for it in issue_items:
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

RISK_RANK = {"高风险": 0, "中风险": 1, "低风险": 2}


def _material_present(materials: list[ExtractedMaterial], *keywords: str) -> bool:
    for material in materials:
        haystack = f"{material.material_name} {material.material_type}"
        if all(kw in haystack for kw in keywords):
            return True
    return False


def _template_lookup(materials: list[ExtractedMaterial]) -> dict[str, str]:
    out: dict[str, str] = {}
    for material in materials:
        if material.material_type != "申报模板":
            continue
        for seg in material.segments:
            out[seg.location] = seg.text
    return out


def _section_has_any(lookup: dict[str, str], section: str) -> bool:
    prefixes = [section, f"{section}.", f"{section}["]
    return any(any(k.startswith(p) for p in prefixes) and str(v).strip() for k, v in lookup.items())


def _field_values(lookup: dict[str, str], field_name: str, section: str = "") -> list[str]:
    values: list[str] = []
    for loc, value in lookup.items():
        if section and not (loc.startswith(f"{section}.") or loc.startswith(f"{section}[")):
            continue
        if loc.endswith(f".{field_name}") or loc == f"{section}.{field_name}":
            values.append(str(value or "").strip())
    return values


def _any_field_equals(lookup: dict[str, str], field_name: str, expected: str, section: str = "") -> bool:
    return any(value == expected for value in _field_values(lookup, field_name, section))


def _get_rule(rules_by_id: dict[str, Rule], rule_id: str) -> Optional[Rule]:
    return rules_by_id.get(rule_id)


def _issue_from_rule(
    rule: Rule,
    *,
    summary: str,
    material_name: str,
    location: str,
    value: str,
    suggestion: str,
    rule_ids: Optional[list[str]] = None,
    rules_by_id: Optional[dict[str, Rule]] = None,
) -> Issue:
    ids = rule_ids or [rule.rule_id]
    bases: list[RuleBasis] = []
    dimensions: list[str] = []
    for rid in ids:
        r = (rules_by_id or {}).get(rid)
        if not r:
            continue
        bases.append(
            RuleBasis(
                basis_type="用户新增规则" if rid.startswith("USER-") else "内置规则",
                basis_file=r.basis_file or "",
                rule_text=r.rule_text or "",
            )
        )
        dimensions.append(r.review_dimension)
    return Issue(
        issue_id="",
        rule_id=rule.rule_id,
        review_dimension=rule.review_dimension,
        issue_summary=summary,
        risk_level=rule.risk_level,
        rule_basis=bases[0] if bases else RuleBasis(basis_file=rule.basis_file, rule_text=rule.rule_text),
        issue_location=[
            IssueLocation(
                material_name=material_name,
                location=location,
                value=value,
            )
        ],
        suggestion=suggestion,
        severity_type=rule.severity_type,
        issue_type=rule.issue_type,
        rule_ids=ids,
        rule_dimensions=dimensions,
        rule_bases=bases,
    )


def _pre_registration_deterministic_issues(
    rules_by_id: dict[str, Rule],
    materials: list[ExtractedMaterial],
) -> list[Issue]:
    issues: list[Issue] = []
    has_application = _material_present(materials, "申请书")
    has_commitment = _material_present(materials, "合规承诺")
    if not has_application:
        rule = _get_rule(rules_by_id, "PREG-FILE-AI-001") or _get_rule(rules_by_id, "PREG-ELEMENT-AI-001")
        if rule:
            issues.append(
                _issue_from_rule(
                    rule,
                    summary="未提交预登记申请书",
                    material_name="材料清单",
                    location="预登记申请书",
                    value="缺失:预登记申请书",
                    suggestion="请补充上传预登记申请书PDF。",
                    rule_ids=[rid for rid in ["PREG-FILE-AI-001", "PREG-FILE-AI-002", "PREG-ELEMENT-AI-001"] if rid in rules_by_id],
                    rules_by_id=rules_by_id,
                )
            )
    if not has_commitment:
        rule = _get_rule(rules_by_id, "PREG-ELEMENT-AI-002")
        if rule:
            issues.append(
                _issue_from_rule(
                    rule,
                    summary="未提交合规承诺书",
                    material_name="材料清单",
                    location="合规承诺书",
                    value="缺失:合规承诺书",
                    suggestion="请补充提交合规承诺书，并按要求签字盖章。",
                    rule_ids=[rid for rid in ["PREG-ELEMENT-AI-002"] if rid in rules_by_id],
                    rules_by_id=rules_by_id,
                )
            )
    return issues


def _pre_registration_skip_rule(rule: Rule, lookup: dict[str, str], materials: list[ExtractedMaterial]) -> bool:
    has_application = _material_present(materials, "申请书")
    has_commitment = _material_present(materials, "合规承诺")

    if not has_application and rule.rule_id in {
        "PREG-FILE-AI-001",
        "PREG-FILE-AI-002",
        "PREG-FILE-AI-003",
        "PREG-ELEMENT-AI-001",
        "PREG-ELEMENT-AI-003",
    }:
        return True
    if not has_commitment and rule.rule_id in {"PREG-ELEMENT-AI-002", "PREG-ELEMENT-AI-004"}:
        return True

    # 退回补正、情况说明等规则没有本次退回意见/新型资产服务信托触发事实时不进入 AI。
    if rule.rule_id in {"PREG-FILE-AI-004", "PREG-FILE-AI-007", "PREG-FILE-AI-008"}:
        return True

    if rule.skip_when == "托管信息.是否聘请保（托）管人 != 是":
        return not _any_field_equals(lookup, "是否聘请保（托）管人", "是", "托管信息")

    if "关联交易信息 empty" in rule.skip_when:
        if not _section_has_any(lookup, "关联交易信息"):
            return True
        if "关联交易性质 != 重大关联交易" in rule.skip_when:
            return not _any_field_equals(lookup, "关联交易性质", "重大关联交易", "关联交易信息")

    if rule.skip_when == "房地产项目信息 empty":
        return not _section_has_any(lookup, "房地产项目信息")

    if rule.skip_when == "异地推介信息 empty":
        return not _section_has_any(lookup, "异地推介信息")

    if rule.skip_when == "底层资产及交易对手.交易对手是否隐债主体 != 是":
        return not _any_field_equals(lookup, "交易对手是否隐债主体", "是", "底层资产及交易对手")

    # 风险分级规则只在触发字段有真实非空值时进入 AI。
    if rule.severity_type == "risk_hint" and rule.field_anchor:
        if not any(_field_values(lookup, rule.field_anchor, section) for section in ("底层资产及交易对手", "房地产项目信息", "异地推介信息", "关联交易信息", "")):
            return True

    return False


def _preprocess_pre_registration_rules(
    rules: list[Rule],
    materials: list[ExtractedMaterial],
) -> tuple[list[Rule], list[Issue], int]:
    rules_by_id = {r.rule_id: r for r in rules}
    lookup = _template_lookup(materials)
    deterministic = _pre_registration_deterministic_issues(rules_by_id, materials)
    filtered = [r for r in rules if not _pre_registration_skip_rule(r, lookup, materials)]
    return filtered, deterministic, len(rules) - len(filtered)


TERMINATION_FIELD_ANCHORS = [
    "清算报告日期",
    "实际到期日期",
    "是否按约定日期清算",
    "是否已完成信托财产分配",
    "是否已完成销户",
    "累计实收信托",
    "日均实收信托",
    "实际收益",
    "信托费用",
    "受托人累计基本报酬",
    "受托人累计业绩报酬",
    "信托收益累计分配额",
    "信托本金累计给付额",
    "赔付金额",
]

TERMINATION_RULE_ANCHORS = {
    "TERM-ELEMENT-AI-001": "清算报告日期",
    "TERM-ELEMENT-AI-002": "实际到期日期",
    "TERM-ELEMENT-AI-003": "是否按约定日期清算",
    "TERM-ELEMENT-AI-004": "是否已完成信托财产分配",
    "TERM-ELEMENT-AI-005": "是否已完成销户",
    "TERM-ELEMENT-AI-006": "累计实收信托",
    "TERM-ELEMENT-AI-007": "日均实收信托",
    "TERM-ELEMENT-AI-008": "实际收益",
    "TERM-ELEMENT-AI-009": "信托费用",
    "TERM-ELEMENT-AI-010": "受托人累计基本报酬",
    "TERM-ELEMENT-AI-011": "受托人累计业绩报酬",
    "TERM-ELEMENT-AI-012": "信托收益累计分配额",
    "TERM-ELEMENT-AI-013": "信托本金累计给付额",
    "TERM-ELEMENT-AI-014": "赔付金额",
    "TERM-FILE-AI-002": "材料:清算报告",
    "TERM-FILE-AI-003": "责任解除条件",
}

TERMINATION_FIELD_ALIASES = {
    "清算报告日期": ("清算报告日期", "清算报告出具日期", "清算报告出具日", "出具日期"),
    "实际到期日期": ("实际到期日期", "停止计提收益", "宣告结束开始兑付", "开始兑付日"),
    "是否按约定日期清算": ("是否按约定日期清算", "按约定日期清算", "约定到期日", "约定日期清算"),
    "是否已完成信托财产分配": ("是否已完成信托财产分配", "信托财产分配", "财产分配", "收益分配"),
    "是否已完成销户": ("是否已完成销户", "完成销户", "销户", "信托财产专户"),
    "累计实收信托": ("累计实收信托", "累计实收信托规模", "实收信托"),
    "日均实收信托": ("日均实收信托", "实收信托日均数", "日均数"),
    "实际收益": ("实际收益", "全部现金收入", "非现金增值"),
    "信托费用": ("信托费用", "费用合计", "由信托财产承担"),
    "受托人累计基本报酬": ("受托人累计基本报酬", "基本报酬", "固定报酬"),
    "受托人累计业绩报酬": ("受托人累计业绩报酬", "业绩报酬"),
    "信托收益累计分配额": ("信托收益累计分配额", "收益累计分配", "收益分配额"),
    "信托本金累计给付额": ("信托本金累计给付额", "本金累计给付", "本金给付额"),
    "赔付金额": ("赔付金额", "赔偿金额", "赔付"),
}

TERMINATION_BROAD_RULES = {"TERM-FILE-AI-001", "TERM-FILE-AI-004"}


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


def _highest_risk(issues: list[Issue]) -> str:
    return min((it.risk_level for it in issues), key=lambda x: RISK_RANK.get(x, 9))


def _termination_text_for_anchor(issue: Issue) -> str:
    parts = [issue.issue_summary, issue.suggestion, issue.rule_id, issue.review_dimension]
    for loc in issue.issue_location:
        parts.extend([loc.material_name, loc.location, loc.value])
    return " ".join(str(p or "") for p in parts)


def _termination_issue_anchor(
    issue: Issue,
    rules_by_id: Optional[dict[str, Rule]] = None,
) -> str:
    """Return a stable termination fact anchor for broad-vs-field merging."""
    if issue.rule_id in TERMINATION_RULE_ANCHORS:
        return TERMINATION_RULE_ANCHORS[issue.rule_id]

    rule = (rules_by_id or {}).get(issue.rule_id)
    if rule and rule.field_name in TERMINATION_FIELD_ANCHORS:
        return rule.field_name
    if rule and "field_anchor=" in (rule.machine_params or ""):
        for part in rule.machine_params.split(";"):
            part = part.strip()
            if part.startswith("field_anchor="):
                return part.split("=", 1)[1].strip()

    text = _termination_text_for_anchor(issue)
    matches: list[str] = []
    for anchor, aliases in TERMINATION_FIELD_ALIASES.items():
        if any(alias and alias in text for alias in aliases):
            matches.append(anchor)
    if len(matches) == 1:
        return matches[0]
    return ""


def _termination_mentioned_anchors(text: str) -> list[str]:
    anchors: list[str] = []
    for anchor, aliases in TERMINATION_FIELD_ALIASES.items():
        if any(alias and alias in text for alias in aliases):
            anchors.append(anchor)
    return anchors


def _unique_locations(locations: list[IssueLocation]) -> list[IssueLocation]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[IssueLocation] = []
    for loc in locations:
        key = (
            (loc.material_name or "").strip(),
            (loc.location or "").strip(),
            (loc.value or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(loc)
    return unique


def _merge_issue_group(group: list[Issue], *, process: Optional[ProcessType] = None) -> Issue:
    def role_rank(issue: Issue) -> tuple[int, int, int]:
        if process == "termination":
            if issue.rule_id.startswith("TERM-ELEMENT-AI-"):
                return (0, RISK_RANK.get(issue.risk_level, 9), -len(issue.issue_location))
            if issue.rule_id in TERMINATION_BROAD_RULES:
                return (2, RISK_RANK.get(issue.risk_level, 9), -len(issue.issue_location))
            return (1, RISK_RANK.get(issue.risk_level, 9), -len(issue.issue_location))
        return (
            RISK_RANK.get(issue.risk_level, 9),
            -len(_defect_pairs(issue)),
            -len(issue.issue_location),
        )

    ordered = sorted(group, key=role_rank)
    head = ordered[0]
    all_locations = _unique_locations(
        [loc for issue in ordered for loc in issue.issue_location]
    )
    if not all_locations:
        all_locations = head.issue_location

    rule_ids = [head.rule_id]
    rule_dimensions = [head.review_dimension]
    rule_bases = [head.rule_basis]
    alt_summaries: list[str] = []
    alt_suggestions: list[str] = []

    for other in ordered[1:]:
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

    return Issue(
        issue_id=head.issue_id,
        rule_id=head.rule_id,
        review_dimension=head.review_dimension,
        issue_summary=head.issue_summary,
        risk_level=_highest_risk(ordered),
        rule_basis=head.rule_basis,
        issue_location=all_locations,
        suggestion=head.suggestion,
        severity_type=head.severity_type,
        issue_type=head.issue_type,
        rule_ids=rule_ids,
        rule_dimensions=rule_dimensions,
        rule_bases=rule_bases,
        alt_summaries=alt_summaries,
        alt_suggestions=alt_suggestions,
    )


def _merge_termination_issues(
    issues: list[Issue],
    rules_by_id: Optional[dict[str, Rule]] = None,
) -> list[Issue]:
    anchored: dict[tuple[str, str], list[Issue]] = {}
    fallback: list[Issue] = []
    order: list[tuple[str, str]] = []
    for issue in issues:
        anchor = _termination_issue_anchor(issue, rules_by_id)
        if not anchor:
            fallback.append(issue)
            continue
        key = ("termination_anchor", anchor)
        if key not in anchored:
            anchored[key] = []
            order.append(key)
        anchored[key].append(issue)

    merged = [_merge_issue_group(anchored[key], process="termination") for key in order]
    if fallback:
        merged.extend(_merge_issues(fallback))
    return merged


def _termination_material_text(materials: list[ExtractedMaterial]) -> str:
    parts: list[str] = []
    for material in materials:
        parts.append(material.material_name)
        parts.append(material.material_type)
        for segment in material.segments:
            parts.append(segment.text)
    return "\n".join(parts)


def _has_termination_liquidation_report(materials: list[ExtractedMaterial]) -> bool:
    for material in materials:
        haystack = " ".join(
            [material.material_name, material.material_type]
            + [seg.text for seg in material.segments[:3]]
        )
        if "清算报告" in haystack or ("清算" in haystack and "报告" in haystack):
            return True
    return False


def _report_records_anchor(material_text: str, anchor: str) -> bool:
    if not anchor:
        return False
    aliases = TERMINATION_FIELD_ALIASES.get(anchor, (anchor,))
    return any(alias and alias in material_text for alias in aliases)


def _should_drop_termination_issue(
    issue: Issue,
    *,
    has_liquidation_report: bool,
    material_text: str,
    rules_by_id: Optional[dict[str, Rule]] = None,
) -> bool:
    if issue.rule_id == "TERM-FILE-AI-002" and has_liquidation_report:
        return True

    if issue.rule_id != "TERM-FILE-AI-005":
        return False

    text = _termination_text_for_anchor(issue)
    anchor = _termination_issue_anchor(issue, rules_by_id)
    says_unrecorded = any(kw in text for kw in ("未记载", "未载明", "未说明", "未包含", "缺少"))
    if says_unrecorded and _report_records_anchor(material_text, anchor):
        return True
    mentioned_anchors = _termination_mentioned_anchors(text)
    if says_unrecorded and mentioned_anchors:
        if all(_report_records_anchor(material_text, item) for item in mentioned_anchors):
            return True

    # 清算报告明确记载了未完成/未满足状态时，这是字段或责任解除问题，
    # 不是“清算报告未记载对应内容”的佐证材料问题。
    unfinished = any(kw in material_text for kw in ("未完成", "尚未完成", "未销户", "尚未销户", "未全部分配"))
    if unfinished and any(kw in text for kw in ("未完成", "尚未", "未销户", "未分配", "未全部分配")):
        return True
    return False


def _postprocess_issues(
    process: ProcessType,
    issues: list[Issue],
    materials: list[ExtractedMaterial],
    rules_by_id: dict[str, Rule],
) -> list[Issue]:
    if process != "termination":
        return issues

    has_liquidation_report = _has_termination_liquidation_report(materials)
    material_text = _termination_material_text(materials)
    cleaned = [
        issue
        for issue in issues
        if not _should_drop_termination_issue(
            issue,
            has_liquidation_report=has_liquidation_report,
            material_text=material_text,
            rules_by_id=rules_by_id,
        )
    ]
    return _merge_termination_issues(cleaned, rules_by_id)


def _merge_issues(
    issues: list[Issue],
    *,
    process: Optional[ProcessType] = None,
    rules_by_id: Optional[dict[str, Rule]] = None,
) -> list[Issue]:
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
    if process == "termination":
        return _merge_termination_issues(issues, rules_by_id)

    # 第一遍：按 defect_pairs 精确聚类
    initial_clusters: dict = {}
    order_keys: list = []
    no_loc_issues: list[Issue] = []
    for it in issues:
        pairs = _defect_pairs(it)
        if not pairs:
            no_loc_issues.append(it)
            continue
        pairs = frozenset(set(pairs) | {("__SEVERITY__", it.severity_type)})
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
        k = f"NOLOC||{it.severity_type}||{(it.issue_summary or '')[:24]}"
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
                RISK_RANK.get(x.risk_level, 9),
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
                severity_type=head.severity_type,
                issue_type=head.issue_type,
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
    max_concurrency: int = 48,
    progress_cb: Optional[ProgressCallback] = None,
    rule_id_whitelist: Optional[set] = None,
    on_batch_done: Optional[BatchDoneCallback] = None,
    material_slice_enabled: bool = False,
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

    deterministic_issues: list[Issue] = []
    if process == "pre_registration":
        ai_rules, deterministic_issues, skipped_count = _preprocess_pre_registration_rules(
            ai_rules,
            materials,
        )
        await _emit(
            progress_cb,
            f"预登记前置判断完成：确定性问题 {len(deterministic_issues)} 个，跳过未触发规则 {skipped_count} 条，进入 AI 规则 {len(ai_rules)} 条",
        )

    if not ai_rules:
        await _emit(progress_cb, "AI 审核规则为空，跳过 LLM 调用")
        deterministic_issues.sort(key=lambda x: (RISK_RANK.get(x.risk_level, 9), x.rule_id))
        for i, it in enumerate(deterministic_issues, start=1):
            it.issue_id = f"ISSUE-{i:03d}"
        deduped = _merge_issues(deterministic_issues, process=process, rules_by_id={r.rule_id: r for r in all_rules})
        for i, it in enumerate(deduped, start=1):
            it.issue_id = f"DEDUPED-ISSUE-{i:03d}"
        return ReviewResult(
            summary=_summarize(process, deterministic_issues),
            issues=deterministic_issues,
            deduped_summary=_summarize(process, deduped),
            deduped_issues=deduped,
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
                client,
                process,
                group,
                materials,
                rules_by_id,
                batch_id,
                progress_cb,
                material_slice_enabled,
            )
            # O6：批次完成立即推送（流式渲染）
            await _emit_batch_done(on_batch_done, issues, log)
            return issues, log

    batch_results = await asyncio.gather(*[worker(i, g) for i, g in enumerate(groups)])

    # 4. 合并结果
    all_issues: list[Issue] = list(deterministic_issues)
    batch_logs: list[BatchLog] = []
    for issues, log in batch_results:
        all_issues.extend(issues)
        batch_logs.append(log)

    # 4.1 终止登记先做规则语义后处理，减少宽泛规则和具体字段规则的重复命中。
    all_issues = _postprocess_issues(process, all_issues, materials, rules_by_id)

    # 4.2 同一事实错误合并：按 issue_location 指纹/终止登记字段锚点聚类
    raw_count = len(all_issues)
    deduped_issues = _merge_issues(all_issues, process=process, rules_by_id=rules_by_id)
    if raw_count != len(deduped_issues):
        await _emit(
            progress_cb,
            f"问题合并：{raw_count} → {len(deduped_issues)}（同一事实错误的多条规则命中已合并）",
        )

    # 5. 编号 + 排序（高→中→低，规则内按 rule_id 稳定排序）
    all_issues.sort(key=lambda x: (RISK_RANK.get(x.risk_level, 9), x.rule_id))
    for i, it in enumerate(all_issues, start=1):
        it.issue_id = f"ISSUE-{i:03d}"
    deduped_issues.sort(key=lambda x: (RISK_RANK.get(x.risk_level, 9), x.rule_id))
    for i, it in enumerate(deduped_issues, start=1):
        it.issue_id = f"DEDUPED-ISSUE-{i:03d}"

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
        deduped_summary=_summarize(process, deduped_issues),
        deduped_issues=deduped_issues,
        human_review_items=human_items,
        batch_logs=batch_logs,
    )
