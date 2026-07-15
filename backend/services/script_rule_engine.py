"""确定性脚本规则执行器。"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from .schemas import ExtractedMaterial, Issue, IssueLocation, Rule, RuleBasis


SUPPORTED_OPERATORS = {
    "enum",
    "dependent_enum",
    "required",
    "max_length",
    "number_precision",
    "date_format",
    "date_range",
    "regex_match",
    "sequence_contiguous",
    "compare_fields",
    "cross_template_equal",
    "conditional_compare",
    "material_required",
    "conditional_material_required",
}

REVIEW_METHOD_MARK_PREFIX = "__review_method__:"


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


def _material_lookup(materials: list[ExtractedMaterial], material_type: str) -> tuple[dict[str, str], str]:
    lookup: dict[str, str] = {}
    material_name = material_type
    for material in materials:
        if material.material_type != material_type:
            continue
        material_name = material.material_name
        for segment in material.segments:
            lookup[segment.location] = segment.text
    return lookup, material_name


def _value_for_rule(lookup: dict[str, str], rule: Rule) -> tuple[str, str]:
    candidates = []
    if rule.table_name and rule.field_name:
        candidates.append(f"{rule.table_name}.{rule.field_name}")
    if rule.field_anchor:
        candidates.append(rule.field_anchor)
    if rule.field_name:
        candidates.append(rule.field_name)

    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate], candidate
        matches = [key for key in lookup if _field_matches(key, candidate)]
        if not matches and rule.field_name:
            matches = [key for key in lookup if _field_matches(key, rule.field_name)]
        if matches:
            key = sorted(matches, key=len)[0]
            return lookup[key], key
    return "", candidates[0] if candidates else (rule.field_name or rule.rule_name)


def _values_for_field(lookup: dict[str, str], field: str) -> list[tuple[str, str]]:
    field = str(field or "").strip()
    if not field:
        return []
    out: list[tuple[str, str]] = []
    for key, value in lookup.items():
        if _field_matches(key, field):
            out.append((value, key))
    return out


def _required_table_name(rule: Rule) -> str:
    table = str(rule.table_name or "").strip()
    field = str(rule.field_name or "").strip()
    anchor = str(rule.field_anchor or "").strip()
    if not table:
        return ""
    if str(rule.rule_object or "").strip() == "表":
        return table
    if field and field == table:
        return table
    if anchor and _strip_array_indexes(anchor) == table:
        return table
    return ""


def _location_in_table(location: str, table_name: str) -> bool:
    location = str(location or "").strip()
    table_name = str(table_name or "").strip()
    if not location or not table_name:
        return False
    # 支持 "表名.字段"、"表名[0].字段"，以及外层模板名前缀后的
    # "申报模板.表名.字段" / "申报模板.表名[0].字段"。
    pattern = rf"(^|\.){re.escape(table_name)}(?:\[\d+\])?\."
    return re.search(pattern, location) is not None


def _is_table_business_value(location: str, value: str) -> bool:
    if str(value or "").strip() in {"", "无", "null", "None", "[]", "{}", "-"}:
        return False
    field_name = str(location or "").rsplit(".", 1)[-1]
    return _strip_array_indexes(field_name) != "序号"


def _table_has_content(lookup: dict[str, str], table_name: str) -> bool:
    return any(
        _location_in_table(location, table_name) and _is_table_business_value(location, value)
        for location, value in lookup.items()
    )


def _strip_array_indexes(value: str) -> str:
    return re.sub(r"\[\d+\]", "", str(value or "").strip())


def _array_scope(path: str) -> tuple[str, str] | None:
    match = re.match(r"^(.+?)\[(\d+)\]\.", str(path or "").strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _field_section(field: str) -> str:
    field = _strip_array_indexes(field)
    return field.rsplit(".", 1)[0] if "." in field else ""


def _same_array_section(field: str, target_location: str) -> bool:
    target_scope = _array_scope(target_location)
    if not target_scope:
        return False
    return _field_section(field) == target_scope[0]


def _values_for_field_in_target_row(
    lookup: dict[str, str],
    field: str,
    target_location: str,
) -> list[tuple[str, str]]:
    target_scope = _array_scope(target_location)
    if not target_scope:
        return _values_for_field(lookup, field)
    out: list[tuple[str, str]] = []
    for key, value in lookup.items():
        if _array_scope(key) == target_scope and _field_matches(key, field):
            out.append((value, key))
    return out


def _normalize_field_key(value: str) -> str:
    text = str(value or "").strip()
    text = _strip_array_indexes(text)
    text = re.sub(r"[（(][%％元万元亿元月日]+[）)]", "", text)
    text = text.replace("%", "").replace("％", "")
    text = re.sub(r"\s+", "", text)
    return text


def _field_matches(key: str, field: str) -> bool:
    key = str(key or "").strip()
    field = str(field or "").strip()
    key_no_index = _strip_array_indexes(key)
    field_no_index = _strip_array_indexes(field)
    if (
        key == field
        or key.endswith(f".{field}")
        or key.endswith(field)
        or key_no_index == field_no_index
        or key_no_index.endswith(f".{field_no_index}")
        or key_no_index.endswith(field_no_index)
    ):
        return True
    normalized_key = _normalize_field_key(key)
    normalized_field = _normalize_field_key(field)
    return (
        normalized_key == normalized_field
        or normalized_key.endswith(f".{normalized_field}")
        or normalized_key.endswith(normalized_field)
    )


def _normalize_compare_value(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _issue(rule: Rule, *, summary: str, material_name: str, location: str, value: str, suggestion: str) -> Issue:
    basis_text = rule.basis_text or rule.rule_text
    basis = RuleBasis(
        basis_type="用户新增规则" if rule.rule_source == "上传规则" else "内置规则",
        basis_file=rule.basis_file or rule.source_file or "上传规则",
        rule_text=f"{REVIEW_METHOD_MARK_PREFIX}脚本\n{basis_text}",
    )
    return Issue(
        issue_id="",
        rule_id=rule.rule_id,
        review_dimension=rule.review_dimension,
        issue_summary=summary,
        risk_level=rule.risk_level,
        rule_basis=basis,
        issue_location=[
            IssueLocation(material_name=material_name, location=location, value=value)
        ],
        suggestion=suggestion,
        severity_type=rule.severity_type,
        issue_type=rule.issue_type,
        rule_ids=[rule.rule_id],
        rule_dimensions=[rule.review_dimension],
        rule_bases=[basis],
    )


def _is_blank(value: str) -> bool:
    return value is None or str(value).strip() in {"", "无", "null", "None"}


def _normalize_material_label(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    text = re.sub(r"附件\s*\d+(?:-\d+)*", "", text)
    text = text.replace("信托产品", "")
    text = re.sub(r"[\s_《》【】\[\]（）()、,，;；/\\.-]+", "", text)
    return text


def _decimal(value: str) -> Optional[Decimal]:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _scale(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return abs(exponent) if exponent < 0 else 0


def _material_matches(material: ExtractedMaterial, label: str) -> bool:
    haystack = f"{material.material_name} {material.material_type}"
    parts = [p for p in re.split(r"[、,，;；/\s]+", label or "") if p]
    if not parts:
        return False
    if any(part in haystack for part in parts):
        return True
    if "模板" in label and material.material_type == "申报模板":
        return True
    if "申请书" in label and material.material_type == "申请书":
        return True
    if ("信托文件" in label or "信托合同" in label) and material.material_type == "信托文件样本":
        return True
    if "清算报告" in label and material.material_type == "其他附件":
        return True

    normalized_label = _normalize_material_label(label)
    normalized_haystack = _normalize_material_label(haystack)
    if normalized_label and normalized_label in normalized_haystack:
        return True

    normalized_parts = [_normalize_material_label(part) for part in parts]
    return any(part and part in normalized_haystack for part in normalized_parts)


def _has_material(materials: list[ExtractedMaterial], label: str, exts: list[str] | None = None) -> bool:
    for material in materials:
        if not _material_matches(material, label):
            continue
        if exts:
            lower = material.material_name.lower()
            if not any(lower.endswith(f".{ext.lower().lstrip('.')}") for ext in exts):
                continue
        return True
    return False


def _trigger_satisfied(rule: Rule, lookup: dict[str, str], materials: list[ExtractedMaterial]) -> bool:
    trigger = rule.trigger_condition or ""
    if not trigger:
        return True
    if "政信类业务=true" in trigger:
        return any("政信" in f"{m.material_name} {m.material_type}" for m in materials) or any(
            value == "是" for key, value in lookup.items() if "交易对手是否隐债主体" in key
        )
    if "新型资产服务信托" in trigger:
        return any(value == "新型资产服务信托" for key, value in lookup.items() if "资产服务信托分类2" in key)
    match = re.search(r"([^=；;]+)=([^；;]+)", trigger)
    if match:
        field = match.group(1).strip()
        expected = match.group(2).strip()
        return any(key.endswith(field) and str(value).strip() == expected for key, value in lookup.items())
    return False


def _match_value(value: str, op: str, expected=None, values=None) -> bool:
    text = str(value or "").strip()
    vals = [str(v).strip() for v in (values or [])]
    exp = "" if expected is None else str(expected).strip()
    if op == "equals":
        return text == exp
    if op == "not_equals":
        return text != exp
    if op == "contains":
        return exp in text
    if op == "not_contains":
        return exp not in text
    if op == "in":
        return text in vals
    if op == "contains_any":
        return any(v and v in text for v in vals)
    if op == "contains_all":
        return all(v and v in text for v in vals)
    if op == "not_contains_all":
        return not all(v and v in text for v in vals)
    if op == "not_blank":
        return not _is_blank(text)
    if op == "blank":
        return _is_blank(text)
    return False


def _is_multi_select_enum(rule: Rule, params: dict) -> bool:
    if params.get("multi_select") is True:
        return True
    text = " ".join(
        str(item or "")
        for item in (rule.rule_text, rule.basis_text, rule.check_type)
    )
    return re.search(r"枚举值\s*[（(]\s*复选\s*[）)]", text) is not None


def _split_multi_select_value(value: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"[、,，;；/\n]+", str(value or ""))
        if item.strip()
    ]


def _allowed_enum_values(values) -> list[str]:
    out: list[str] = []
    for value in values or []:
        for item in re.split(r"[、,，;；\n]+", str(value or "")):
            item = item.strip()
            if item and item not in out:
                out.append(item)
    return out


def _condition_satisfied(cond: dict, lookup: dict[str, str]) -> bool:
    if not cond:
        return True
    if "conditions" in cond:
        logic = str(cond.get("logic") or "AND").upper()
        checks = [_condition_satisfied(c, lookup) for c in cond.get("conditions") or [] if isinstance(c, dict)]
        return any(checks) if logic == "OR" else all(checks)
    field = cond.get("field") or ""
    matches = _values_for_field(lookup, field)
    if not matches:
        return False
    op = cond.get("op") or "equals"
    return any(_match_value(value, op, cond.get("value"), cond.get("values")) for value, _ in matches)


def _condition_satisfied_for_target_row(
    cond: dict,
    lookup: dict[str, str],
    target_location: str,
) -> bool:
    if not cond:
        return True
    if "conditions" in cond:
        logic = str(cond.get("logic") or "AND").upper()
        checks = [
            _condition_satisfied_for_target_row(c, lookup, target_location)
            for c in cond.get("conditions") or []
            if isinstance(c, dict)
        ]
        return any(checks) if logic == "OR" else all(checks)

    field = cond.get("field") or ""
    if _same_array_section(field, target_location):
        matches = _values_for_field_in_target_row(lookup, field, target_location)
    else:
        matches = _values_for_field(lookup, field)
    if not matches:
        return False
    op = cond.get("op") or "equals"
    return any(_match_value(value, op, cond.get("value"), cond.get("values")) for value, _ in matches)


def _target_issue(
    rule: Rule,
    *,
    template_name: str,
    location: str,
    value: str,
    summary: str,
    suggestion: str,
) -> Issue:
    return _issue(
        rule,
        summary=summary,
        material_name=template_name,
        location=location,
        value=value,
        suggestion=suggestion,
    )


def _run_target_check(
    rule: Rule,
    target: dict,
    lookup: dict[str, str],
    template_name: str,
    trigger: dict | None = None,
) -> list[Issue]:
    field = target.get("field") or rule.field_anchor or rule.field_name
    op = target.get("op") or "required"
    matches = _values_for_field(lookup, field)
    if not matches:
        matches = [("", field)]
    issues: list[Issue] = []
    label = str(field).split(".")[-1]

    for value, location in matches:
        if trigger and not _condition_satisfied_for_target_row(trigger, lookup, location):
            continue
        if op == "required":
            if _is_blank(value):
                issues.append(_target_issue(rule, template_name=template_name, location=location, value=value, summary=f"{label}在触发条件下为必填项但未填写", suggestion="请按规则要求补充填写该字段。"))
        elif op in {"equals", "not_equals", "contains", "not_contains", "in", "contains_any", "contains_all", "not_contains_all"}:
            ok = _match_value(value, op, target.get("value"), target.get("values"))
            if not ok:
                expected = target.get("value") if target.get("value") is not None else "、".join(target.get("values") or [])
                issues.append(_target_issue(rule, template_name=template_name, location=location, value=value, summary=f"{label}不满足规则要求：{op} {expected}", suggestion="请按规则要求核对字段取值。"))
        elif op in {"lte_field", "gte_field"}:
            other_field = target.get("other_field") or target.get("right_field")
            other_matches = (
                _values_for_field_in_target_row(lookup, other_field, location)
                if _same_array_section(other_field, location)
                else _values_for_field(lookup, other_field)
            )
            if not other_matches:
                continue
            left = _decimal(value)
            right_value, right_location = other_matches[0]
            right = _decimal(right_value)
            if left is None or right is None:
                continue
            failed = left > right if op == "lte_field" else left < right
            if failed:
                relation = "不得大于" if op == "lte_field" else "不得小于"
                issues.append(_target_issue(rule, template_name=template_name, location=f"{location}; {right_location}", value=f"{value}; {right_value}", summary=f"{label}{relation}{other_field}", suggestion="请核对两个字段的数值关系。"))
        elif op == "range":
            number = _decimal(value)
            if number is None:
                continue
            min_value = target.get("min")
            max_value = target.get("max")
            failed = False
            if min_value is not None and number < Decimal(str(min_value)):
                failed = True
            if max_value is not None and number > Decimal(str(max_value)):
                failed = True
            if failed:
                issues.append(_target_issue(rule, template_name=template_name, location=location, value=value, summary=f"{label}不在允许范围内", suggestion="请按规则要求调整数值范围。"))
    return issues


def run_script_rules(rules: list[Rule], materials: list[ExtractedMaterial]) -> tuple[list[Issue], list[str], list[str]]:
    lookup, template_name = _template_lookup(materials)
    issues: list[Issue] = []
    logs: list[str] = []
    fallback_rule_ids: list[str] = []

    for rule in rules:
        op = rule.operator
        params = rule.script_params or {}
        if op not in SUPPORTED_OPERATORS:
            logs.append(f"跳过脚本规则 {rule.rule_id}：operator={op} 暂未结构化执行")
            fallback_rule_ids.append(rule.rule_id)
            continue
        if not _trigger_satisfied(rule, lookup, materials):
            continue

        if op in {"material_required", "conditional_material_required"}:
            label = params.get("material_label") or rule.rule_name or rule.field_name
            exts = params.get("file_ext") if isinstance(params.get("file_ext"), list) else None
            if not _has_material(materials, label, exts):
                issues.append(
                    _issue(
                        rule,
                        summary=f"未提交或未识别到{label}",
                        material_name="材料清单",
                        location=label,
                        value=f"缺失:{label}",
                        suggestion=f"请补充上传{label}。",
                    )
                )
            continue

        if op == "cross_template_equal":
            baseline_lookup, baseline_name = _material_lookup(materials, "上一次登记申报模板")
            if not baseline_lookup:
                logs.append(f"跳过脚本规则 {rule.rule_id}：缺少上一次登记申报模板")
                continue
            current_field = params.get("current_field") or params.get("field_path") or rule.field_anchor or rule.field_name
            baseline_field = params.get("baseline_field") or params.get("field_path") or rule.field_anchor or rule.field_name
            current_matches = _values_for_field(lookup, str(current_field))
            baseline_matches = _values_for_field(baseline_lookup, str(baseline_field))
            if not current_matches or not baseline_matches:
                continue
            for current_value, current_location in current_matches:
                current_suffix = current_location.split(".", 1)[-1]
                baseline_value, baseline_location = baseline_matches[0]
                for item_value, item_location in baseline_matches:
                    if item_location.endswith(current_suffix):
                        baseline_value, baseline_location = item_value, item_location
                        break
                if _normalize_compare_value(current_value) == _normalize_compare_value(baseline_value):
                    continue
                label = rule.field_name or rule.rule_name or str(current_field).split(".")[-1]
                issues.append(
                    _issue(
                        rule,
                        summary=f"{label}不在变更登记范围内但发生变更",
                        material_name=template_name,
                        location=f"{current_location}; 对比:{baseline_name}.{baseline_location}",
                        value=f"本次:{current_value}; 上一次:{baseline_value}",
                        suggestion="请保持该字段与上一次登记申报模板一致，或确认其属于允许变更字段后调整规则。",
                    )
                )
            continue

        if op == "conditional_compare":
            trigger = params.get("trigger") if isinstance(params.get("trigger"), dict) else {}
            target = params.get("target") if isinstance(params.get("target"), dict) else {}
            if not target:
                logs.append(f"跳过脚本规则 {rule.rule_id}：缺少target")
                fallback_rule_ids.append(rule.rule_id)
                continue
            issues.extend(_run_target_check(rule, target, lookup, template_name, trigger=trigger))
            continue

        if op == "dependent_enum":
            parent_field = str(params.get("parent_field") or "").strip()
            child_field = str(params.get("child_field") or "").strip()
            mapping = params.get("mapping")
            if not parent_field or not child_field or not isinstance(mapping, dict) or not mapping:
                logs.append(f"跳过脚本规则 {rule.rule_id}：dependent_enum 参数不完整")
                continue
            child_matches = _values_for_field(lookup, child_field)
            for child_value, child_location in child_matches:
                if _is_blank(child_value):
                    continue
                parent_matches = _values_for_field_in_target_row(lookup, parent_field, child_location)
                if not parent_matches:
                    continue
                parent_value, parent_location = parent_matches[0]
                allowed = _allowed_enum_values(mapping.get(str(parent_value).strip()) or [])
                if not allowed or str(child_value).strip() in allowed:
                    continue
                issues.append(
                    _issue(
                        rule,
                        summary=f"{child_field}与{parent_field}的地区映射不一致",
                        material_name=template_name,
                        location=f"{parent_location}; {child_location}",
                        value=f"{parent_field}:{parent_value}; {child_field}:{child_value}",
                        suggestion=f"请将{child_field}修改为{parent_field}对应的有效地区。",
                    )
                )
            continue

        if op == "required":
            table_name = _required_table_name(rule)
            if table_name:
                if not _table_has_content(lookup, table_name):
                    issues.append(
                        _issue(
                            rule,
                            summary=f"{table_name}表未填写",
                            material_name=template_name,
                            location=table_name,
                            value=f"空表:{table_name}",
                            suggestion=f"请补充填写{table_name}表。",
                        )
                    )
                continue

            value, location = _value_for_rule(lookup, rule)
            if _is_blank(value):
                issues.append(
                    _issue(
                        rule,
                        summary=f"{rule.field_name or rule.rule_name}为必填项但未填写",
                        material_name=template_name,
                        location=location,
                        value=value,
                        suggestion="请补充填写该字段。",
                    )
                )
            continue

        value, location = _value_for_rule(lookup, rule)
        if _is_blank(value):
            continue

        if op == "enum":
            allowed = _allowed_enum_values(params.get("values") or [])
            if not allowed:
                logs.append(f"跳过脚本规则 {rule.rule_id}：enum 缺少非空 values")
                continue
            if allowed and _is_multi_select_enum(rule, params):
                selected = _split_multi_select_value(value)
                invalid_values = [item for item in selected if item not in allowed]
                if selected and not invalid_values:
                    continue
                issue_value = "、".join(invalid_values) if invalid_values else value
                issues.append(
                    _issue(
                        rule,
                        summary=f"{rule.field_name or rule.rule_name}不在允许的枚举值范围内",
                        material_name=template_name,
                        location=location,
                        value=issue_value,
                        suggestion="请按规则要求选择有效枚举值。",
                    )
                )
            elif allowed and value not in allowed:
                issues.append(
                    _issue(
                        rule,
                        summary=f"{rule.field_name or rule.rule_name}不在允许的枚举值范围内",
                        material_name=template_name,
                        location=location,
                        value=value,
                        suggestion="请按规则要求选择有效枚举值。",
                    )
                )
        elif op == "max_length":
            max_len = params.get("max_length")
            if isinstance(max_len, int) and len(value) > max_len:
                issues.append(
                    _issue(
                        rule,
                        summary=f"{rule.field_name or rule.rule_name}长度超过{max_len}个字符",
                        material_name=template_name,
                        location=location,
                        value=value,
                        suggestion=f"请将该字段长度控制在{max_len}个字符以内。",
                    )
                )
        elif op == "number_precision":
            number = _decimal(value)
            if number is None:
                issues.append(
                    _issue(
                        rule,
                        summary=f"{rule.field_name or rule.rule_name}不是有效数值",
                        material_name=template_name,
                        location=location,
                        value=value,
                        suggestion="请按数值格式填写。",
                    )
                )
                continue
            scale = params.get("scale")
            if isinstance(scale, int) and _scale(number) > scale:
                issues.append(
                    _issue(
                        rule,
                        summary=f"{rule.field_name or rule.rule_name}小数位数超过{scale}位",
                        material_name=template_name,
                        location=location,
                        value=value,
                        suggestion=f"请保留不超过{scale}位小数。",
                    )
                )
        elif op == "date_format":
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                issues.append(
                    _issue(
                        rule,
                        summary=f"{rule.field_name or rule.rule_name}日期格式不是YYYY-MM-DD",
                        material_name=template_name,
                        location=location,
                        value=value,
                        suggestion="请按YYYY-MM-DD格式填写有效日期。",
                    )
                )
        elif op == "date_range":
            try:
                actual = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                logs.append(f"跳过脚本规则 {rule.rule_id}：日期格式不符合YYYY-MM-DD，交由date_format规则处理")
                continue
            today = datetime.now().date()
            if params.get("min") == "today" and actual < today:
                issues.append(_issue(rule, summary=f"{rule.field_name or rule.rule_name}早于当前系统日期", material_name=template_name, location=location, value=value, suggestion="请填写不早于当前系统日期的日期。"))
                continue
            max_days = params.get("max_days")
            if isinstance(max_days, int) and (actual - today).days > max_days:
                issues.append(_issue(rule, summary=f"{rule.field_name or rule.rule_name}晚于合理业务期限", material_name=template_name, location=location, value=value, suggestion=f"请填写当前日期起{max_days}天内的日期。"))
        elif op == "regex_match":
            pattern = params.get("pattern")
            if pattern and not re.fullmatch(str(pattern), value):
                issues.append(_issue(rule, summary=f"{rule.field_name or rule.rule_name}不符合编码或格式规范", material_name=template_name, location=location, value=value, suggestion="请按规则要求填写标准编码或格式。"))
        elif op == "sequence_contiguous":
            matches = _values_for_field(lookup, rule.field_anchor or rule.field_name)
            nums = []
            bad = []
            for item, loc in matches:
                try:
                    nums.append(int(str(item).strip()))
                except ValueError:
                    bad.append((item, loc))
            if bad or (nums and sorted(nums) != list(range(1, len(nums) + 1))):
                issues.append(_issue(rule, summary=f"{rule.field_name or rule.rule_name}应为连续自然数序号", material_name=template_name, location=location, value="、".join(str(n) for n in nums), suggestion="请按1开始的连续自然数填写序号。"))
        elif op == "compare_fields":
            right_field = params.get("right_field")
            if not right_field:
                logs.append(f"跳过脚本规则 {rule.rule_id}：缺少right_field")
                fallback_rule_ids.append(rule.rule_id)
                continue
            right_value = ""
            right_location = ""
            for key, item in lookup.items():
                if key.endswith(str(right_field)):
                    right_value = item
                    right_location = key
                    break
            left = _decimal(value)
            right = _decimal(right_value)
            if left is not None and right is not None and left > right:
                issues.append(
                    _issue(
                        rule,
                        summary=f"{rule.field_name or rule.rule_name}不得大于{right_field}",
                        material_name=template_name,
                        location=f"{location}; {right_location}",
                        value=f"{value}; {right_value}",
                        suggestion="请核对两个字段的数值关系。",
                    )
                )
    return issues, logs, fallback_rule_ids
