"""Evaluate table-level reporting scope before field-level review rules."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from .schemas import (
    ExtractedMaterial,
    HumanReviewItem,
    Issue,
    IssueLocation,
    Rule,
    RuleBasis,
    ScopeDecision,
    TableScopeRule,
)


TABLE_ALIASES = {
    "关联交易事项": "关联交易信息",
    "关联交易信息": "关联交易信息",
}


def normalize_table_name(value: str) -> str:
    text = re.sub(r"^\s*\d+\s*[.、．]\s*", "", str(value or "")).strip()
    return TABLE_ALIASES.get(text, text)


def _strip_indexes(value: str) -> str:
    return re.sub(r"\[\d+\]", "", str(value or ""))


def _normalized_path(value: str) -> str:
    parts = [_strip_indexes(part).strip() for part in str(value or "").split(".") if part.strip()]
    return ".".join(TABLE_ALIASES.get(part, part) for part in parts)


def _template_lookup(materials: list[ExtractedMaterial]) -> tuple[dict[str, str], str]:
    lookup: dict[str, str] = {}
    material_name = "申报模板"
    for material in materials:
        if material.material_type != "申报模板":
            continue
        material_name = material.material_name
        for segment in material.segments:
            lookup[segment.location] = segment.text
    return lookup, material_name


def _path_matches(location: str, field: str) -> bool:
    left = _normalized_path(location)
    right = _normalized_path(field)
    return left == right or left.endswith(f".{right}")


def _values_for_field(lookup: dict[str, str], field: str) -> list[tuple[str, str]]:
    return [(str(value or "").strip(), location) for location, value in lookup.items() if _path_matches(location, field)]


def _location_in_table(location: str, table_name: str) -> bool:
    path = _normalized_path(location)
    table = normalize_table_name(table_name)
    return path == table or f".{table}." in f".{path}." or f".{table}[" in str(location)


def table_has_content(lookup: dict[str, str], table_name: str) -> bool:
    for location, value in lookup.items():
        if not _location_in_table(location, table_name):
            continue
        field = _strip_indexes(str(location).rsplit(".", 1)[-1])
        if field == "序号":
            continue
        if str(value or "").strip() not in {"", "无", "null", "None", "[]", "{}", "-"}:
            return True
    return False


def _match_value(value: str, op: str, expected: Any = None, values: list[Any] | None = None) -> bool:
    text = str(value or "").strip()
    expected_text = "" if expected is None else str(expected).strip()
    allowed = [str(item).strip() for item in (values or [])]
    if op == "equals":
        return text == expected_text
    if op == "not_equals":
        return text != expected_text
    if op == "in":
        return text in allowed
    if op == "not_in":
        return text not in allowed
    if op == "contains":
        return bool(expected_text) and expected_text in text
    if op == "contains_any":
        return any(item and item in text for item in allowed)
    if op == "not_blank":
        return text not in {"", "无", "null", "None", "-"}
    if op == "blank":
        return text in {"", "无", "null", "None", "-"}
    return False


def condition_satisfied(condition: dict, lookup: dict[str, str]) -> bool:
    if not condition:
        return False
    conditions = condition.get("conditions")
    if isinstance(conditions, list):
        checks = [condition_satisfied(item, lookup) for item in conditions if isinstance(item, dict)]
        if not checks:
            return False
        return any(checks) if str(condition.get("logic") or "AND").upper() == "OR" else all(checks)
    if condition.get("op") == "table_has_content":
        return table_has_content(lookup, str(condition.get("table") or condition.get("value") or ""))
    field = str(condition.get("field") or "")
    matches = _values_for_field(lookup, field)
    if not matches:
        return False
    op = str(condition.get("op") or "equals")
    return any(_match_value(value, op, condition.get("value"), condition.get("values")) for value, _ in matches)


def _parse_date(value: str) -> date | None:
    text = str(value or "").strip().replace("/", "-")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def _submission_date(lookup: dict[str, str]) -> tuple[date | None, str, str]:
    matches = _values_for_field(lookup, "申报日期")
    for value, location in matches:
        parsed = _parse_date(value)
        if parsed:
            return parsed, location, value
    return None, "申报日期", ""


def evaluate_deterministic_scopes(
    scopes: list[TableScopeRule],
    materials: list[ExtractedMaterial],
) -> list[ScopeDecision]:
    lookup, template_name = _template_lookup(materials)
    submission_date, date_location, date_value = _submission_date(lookup)
    decisions: list[ScopeDecision] = []
    for scope in scopes:
        if not scope.enabled:
            continue
        present = table_has_content(lookup, scope.table_name)
        evidence: list[IssueLocation] = []
        status = "unknown"
        reason = "结构化材料不足，无法确定该表是否应填报"

        start = _parse_date(scope.effective_from)
        end = _parse_date(scope.effective_to)
        if (start or end) and submission_date is None:
            reason = "未识别到有效申报日期，无法执行报送范围时点规则"
        elif start and submission_date and submission_date < start:
            status = scope.outside_effect
            reason = f"申报日期早于范围规则生效日期 {scope.effective_from}"
        elif end and submission_date and submission_date > end:
            status = scope.outside_effect
            reason = f"申报日期晚于范围规则失效日期 {scope.effective_to}"
        elif scope.scope_type == "always_required":
            status = "required"
            reason = f"该表要求全部{scope.registration_type}项目填报"
        elif scope.scope_type == "prohibited":
            status = "prohibited"
            reason = "该表在当前范围规则下不再填报"
        else:
            applicable = condition_satisfied(scope.applicability_condition, lookup)
            exempt = condition_satisfied(scope.exemption_condition, lookup)
            if applicable and exempt:
                status = "conflict"
                reason = "结构化字段同时命中适用和豁免条件"
            elif applicable:
                status = "required"
                reason = "结构化字段命中该表适用条件"
            elif exempt:
                status = "not_required"
                reason = "结构化字段命中该表豁免条件"

        if submission_date and (start or end):
            evidence.append(IssueLocation(material_name=template_name, location=date_location, value=date_value))
        decisions.append(
            ScopeDecision(
                scope_id=scope.scope_id,
                table_name=normalize_table_name(scope.table_name),
                status=status,
                reason=reason,
                source="script",
                table_present=present,
                evidence=evidence,
            )
        )
    return decisions


def _material_matches(material: ExtractedMaterial, labels: list[str]) -> bool:
    if not labels:
        return material.material_type in {"申报模板", "申请书"}
    haystack = f"{material.material_name} {material.material_type}"
    return any(label in haystack or (label == "申报模板" and material.material_type == "申报模板") for label in labels)


def _scope_messages(
    scopes: list[TableScopeRule],
    materials: list[ExtractedMaterial],
) -> list[dict[str, str]]:
    registration_types = "、".join(sorted({scope.registration_type for scope in scopes if scope.registration_type})) or "信托登记"
    labels = sorted({label for scope in scopes for label in scope.ai_materials})
    material_blocks: list[str] = []
    total_chars = 0
    for material in materials:
        if not _material_matches(material, labels):
            continue
        lines = [f"### 材料：{material.material_name}（{material.material_type}）"]
        for segment in material.segments:
            text = str(segment.text or "")[:1200]
            line = f"[{segment.location}] {text}"
            if total_chars + len(line) > 40000:
                break
            lines.append(line)
            total_chars += len(line)
        material_blocks.append("\n".join(lines))
    scope_objects = [
        {
            "scope_id": scope.scope_id,
            "registration_type": scope.registration_type,
            "table_name": scope.table_name,
            "rule_text": scope.rule_text,
            "ai_check_focus": scope.ai_check_focus,
        }
        for scope in scopes
    ]
    system = f"""你是信托产品{registration_types}表级报送范围判断助手。只判断给定数据表是否应填报，不审核表内字段质量。表为空不能直接推断为无需填报。必须结合规则指定的申报模板、申请书、信托文件或其他申请材料事实，返回合法JSON，不得输出markdown。status只能是required、not_required、unknown、conflict。证据必须来自材料原文。"""
    example_scope_id = scopes[0].scope_id if scopes else "SCOPE-001"
    user = f"""## 范围规则
{json.dumps(scope_objects, ensure_ascii=False, indent=2)}

## 申请材料
{chr(10).join(material_blocks) if material_blocks else '无可用申请材料'}

## 输出结构
{{"scope_decisions":[{{"scope_id":"{example_scope_id}","status":"required","reason":"判断理由","evidence":[{{"material_name":"材料名","location":"真实位置","value":"原文"}}]}}]}}
每条输入范围规则必须返回一条结果。无法可靠判断时返回unknown。"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def resolve_scope_decisions(
    scopes: list[TableScopeRule],
    materials: list[ExtractedMaterial],
    *,
    client: Any = None,
) -> list[ScopeDecision]:
    decisions = evaluate_deterministic_scopes(scopes, materials)
    by_id = {decision.scope_id: decision for decision in decisions}
    unresolved = [
        scope
        for scope in scopes
        if scope.enabled
        and scope.unknown_policy == "ai_review"
        and by_id.get(scope.scope_id)
        and by_id[scope.scope_id].status in {"unknown", "not_required"}
    ]
    if not unresolved:
        return decisions
    if client is None:
        for scope in unresolved:
            decision = by_id[scope.scope_id]
            decision.status = "unknown"
            decision.reason = "未配置AI范围判断服务，转人工确认"
        return decisions
    try:
        response = await client.chat(_scope_messages(unresolved, materials))
        raw_decisions = response.parsed.get("scope_decisions") or []
    except Exception as exc:
        for scope in unresolved:
            decision = by_id[scope.scope_id]
            decision.status = "unknown"
            decision.reason = f"AI范围判断失败，转人工确认：{exc}"
        return decisions

    allowed = {"required", "not_required", "unknown", "conflict"}
    resolved_ids: set[str] = set()
    for raw in raw_decisions:
        if not isinstance(raw, dict):
            continue
        scope_id = str(raw.get("scope_id") or "")
        decision = by_id.get(scope_id)
        status = str(raw.get("status") or "")
        if decision is None or status not in allowed:
            continue
        resolved_ids.add(scope_id)
        evidence = []
        for item in raw.get("evidence") or []:
            if isinstance(item, dict):
                evidence.append(
                    IssueLocation(
                        material_name=str(item.get("material_name") or ""),
                        location=str(item.get("location") or ""),
                        value=str(item.get("value") or ""),
                    )
                )
        raw_reason = str(raw.get("reason") or "").strip()
        ai_reason = raw_reason or ("AI无法可靠判断，转人工确认" if status == "unknown" else decision.reason)
        if decision.status == "not_required" and status in {"required", "conflict"}:
            decision.status = "conflict"
            decision.reason = f"结构化字段显示无需填报，但申请材料语义判断相反：{ai_reason}"
            decision.source = "script+ai"
        elif status == "unknown":
            decision.status = "unknown"
            decision.reason = ai_reason
            decision.source = "script+ai"
        else:
            decision.status = status
            decision.reason = ai_reason
            decision.source = "script+ai" if decision.source == "script" else "ai"
        if evidence:
            decision.evidence = evidence
    for scope in unresolved:
        if scope.scope_id in resolved_ids:
            continue
        decision = by_id[scope.scope_id]
        decision.status = "unknown"
        decision.reason = "AI范围判断未返回有效结果，转人工确认"
    return decisions


def _scope_issue(scope: TableScopeRule, decision: ScopeDecision, *, summary: str, value: str) -> Issue:
    locations = list(decision.evidence)
    if not locations:
        locations = [IssueLocation(material_name="申报模板", location=scope.table_name, value=value)]
    return Issue(
        issue_id="",
        rule_id=scope.scope_id,
        review_dimension="登记必填要素规则库",
        issue_summary=summary,
        risk_level=scope.risk_level,
        rule_basis=RuleBasis(
            basis_type="内置规则",
            basis_file=scope.basis_text or scope.source_file or "表级报送范围规则",
            rule_text=scope.rule_text,
        ),
        issue_location=locations,
        suggestion=f"请根据报送范围核对并补充或调整{scope.table_name}。",
        issue_type="表级报送范围",
    )


def apply_scope_decisions(
    rules: list[Rule],
    scopes: list[TableScopeRule],
    decisions: list[ScopeDecision],
) -> tuple[list[Rule], list[Issue], list[HumanReviewItem], int]:
    scope_by_id = {scope.scope_id: scope for scope in scopes if scope.enabled}
    decision_by_table = {normalize_table_name(item.table_name): item for item in decisions}
    issues: list[Issue] = []
    human_items: list[HumanReviewItem] = []
    blocked_tables: set[str] = set()

    for decision in decisions:
        scope = scope_by_id.get(decision.scope_id)
        if scope is None:
            continue
        table = normalize_table_name(scope.table_name)
        if decision.status == "required" and not decision.table_present:
            blocked_tables.add(table)
            issues.append(_scope_issue(scope, decision, summary=f"{scope.table_name}属于本项目报送范围但未填写", value=f"缺失:{scope.table_name}"))
        elif decision.status == "prohibited":
            blocked_tables.add(table)
            if decision.table_present:
                issues.append(_scope_issue(scope, decision, summary=f"{scope.table_name}在当前申报时点已不再填报", value=f"已填:{scope.table_name}"))
        elif decision.status == "not_required" and not decision.table_present:
            blocked_tables.add(table)
        elif decision.status == "unknown":
            if not decision.table_present:
                blocked_tables.add(table)
            human_items.append(
                HumanReviewItem(
                    rule_id=scope.scope_id,
                    rule_name=scope.table_name,
                    rule_text=scope.rule_text,
                    reason=decision.reason,
                )
            )
        elif decision.status == "conflict":
            issues.append(_scope_issue(scope, decision, summary=f"关于{scope.table_name}是否应填报的材料信息存在冲突", value="范围判断冲突"))
            if not decision.table_present:
                blocked_tables.add(table)

    filtered: list[Rule] = []
    for rule in rules:
        table = normalize_table_name(rule.table_name)
        decision = decision_by_table.get(table)
        if decision is None or table not in blocked_tables:
            filtered.append(rule)
    return filtered, issues, human_items, len(rules) - len(filtered)
