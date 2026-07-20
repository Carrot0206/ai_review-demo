from __future__ import annotations

import ast
import calendar
import re
import time
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ..models.schemas import ExtractedMaterial, RuleEvidence, RuleExecutionResult
from ..services.rule_library import LibraryRule, SUPPORTED_OPERATORS


class NeedsAIFallback(Exception):
    pass


def _strip_indexes(value: str) -> str:
    return re.sub(r"\[\d+\]", "", str(value or "").strip())


def _normalize_field(value: str) -> str:
    text = _strip_indexes(value)
    text = re.sub(r"^[^.]+申报模板\.", "", text)
    text = re.sub(r"^(?:第?[一二三四五六七八九十百]+[章节部分、.．]|\d+[、.．])\s*", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def _field_matches(location: str, field: str) -> bool:
    location_normalized = _normalize_field(location)
    field_normalized = _normalize_field(field)
    return bool(
        field_normalized
        and (
            location_normalized == field_normalized
            or location_normalized.endswith(f".{field_normalized}")
            or location_normalized.endswith(field_normalized)
        )
    )


def _array_scope(location: str) -> str:
    match = re.search(r"(.+?\[\d+\])\.", str(location or ""))
    return match.group(1) if match else ""


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() in {"", "无", "null", "None", "-"}


def _decimal(value: Any) -> Decimal | None:
    text = str(value or "").replace(",", "").replace("%", "").replace("％", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _date(value: Any) -> date | None:
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _material_label_matches(material: ExtractedMaterial, label: str) -> bool:
    label = str(label or "").strip()
    haystack = f"{material.material_name} {material.material_type}"
    if not label:
        return True
    if label in haystack or material.material_type in label:
        return True
    if "模板" in label and material.material_type == "申报模板":
        return True
    if "申请书" in label and material.material_type == "申请书":
        return True
    if ("信托文件" in label or "信托合同" in label) and material.material_type == "信托文件样本":
        return True
    if ("清算报告" in label or "其他附件" in label) and material.material_type == "其他附件":
        return True
    return False


class MaterialIndex:
    def __init__(self, materials: list[ExtractedMaterial]) -> None:
        self.materials = materials
        self.entries: list[tuple[ExtractedMaterial, str, str]] = [
            (material, segment.location, segment.text)
            for material in materials
            for segment in material.segments
        ]

    def values(
        self,
        field: str,
        *,
        labels: list[str] | None = None,
        material_type: str | None = None,
        target_location: str = "",
    ) -> list[tuple[str, str, str]]:
        target_scope = _array_scope(target_location)
        matches: list[tuple[str, str, str]] = []
        for material, location, value in self.entries:
            if material_type and material.material_type != material_type:
                continue
            if labels and not any(_material_label_matches(material, label) for label in labels):
                continue
            if target_scope and _array_scope(location) and _array_scope(location) != target_scope:
                continue
            if _field_matches(location, field):
                matches.append((value, location, material.material_name))
        return matches

    def materials_matching(self, label: str) -> list[ExtractedMaterial]:
        return [material for material in self.materials if _material_label_matches(material, label)]


def _split_multi(value: Any) -> list[str]:
    return [item.strip() for item in re.split(r"[、,，;；/\n]+", str(value or "")) if item.strip()]


def _match(value: Any, operator: str, *, expected: Any = None, values: list[Any] | None = None) -> bool:
    text = str(value or "").strip()
    expected_text = str(expected or "").strip()
    allowed = [str(item).strip() for item in values or []]
    if operator == "equals":
        return text == expected_text
    if operator == "not_equals":
        return text != expected_text
    if operator == "contains":
        return expected_text in text
    if operator == "not_contains":
        return expected_text not in text
    if operator == "in":
        return text in allowed
    if operator == "contains_any":
        return any(item and item in text for item in allowed)
    if operator == "contains_all":
        return all(item and item in text for item in allowed)
    if operator == "not_contains_all":
        return not all(item and item in text for item in allowed)
    if operator == "blank":
        return _blank(text)
    if operator == "not_blank":
        return not _blank(text)
    raise NeedsAIFallback(f"不支持的条件操作符：{operator}")


def _condition_satisfied(condition: dict[str, Any], index: MaterialIndex, target_location: str = "") -> bool:
    if not condition:
        return True
    children = condition.get("conditions")
    if isinstance(children, list):
        checks = [
            _condition_satisfied(child, index, target_location)
            for child in children
            if isinstance(child, dict)
        ]
        return any(checks) if str(condition.get("logic") or "AND").upper() == "OR" else all(checks)
    field = str(condition.get("field") or "")
    operator = str(condition.get("op") or "equals")
    matches = index.values(field, target_location=target_location)
    if operator in {"date_gte", "date_lte", "date_gt", "date_lt"}:
        expected = _date(condition.get("value"))
        if expected is None:
            raise NeedsAIFallback("日期触发条件缺少有效日期")
        for value, _, _ in matches:
            actual = _date(value)
            if actual is None:
                continue
            if operator == "date_gte" and actual >= expected:
                return True
            if operator == "date_lte" and actual <= expected:
                return True
            if operator == "date_gt" and actual > expected:
                return True
            if operator == "date_lt" and actual < expected:
                return True
        return False
    return any(
        _match(value, operator, expected=condition.get("value"), values=condition.get("values"))
        for value, _, _ in matches
    )


def _evidence(matches: list[tuple[str, str, str]], fallback_location: str = "") -> list[RuleEvidence]:
    if not matches:
        return [RuleEvidence(location=fallback_location, value=f"缺失:{fallback_location.split('.')[-1]}")]
    return [RuleEvidence(material_name=material, location=location, value=value) for value, location, material in matches]


def _failed(
    rule: LibraryRule,
    summary: str,
    evidence: list[RuleEvidence],
    suggestion: str = "请按规则要求核对并修正。",
) -> RuleExecutionResult:
    return RuleExecutionResult(
        rule_id=rule.rule_id,
        status="failed",
        execution_method="script",
        summary=summary,
        suggestion=suggestion,
        evidence=evidence,
    )


def _passed(rule: LibraryRule) -> RuleExecutionResult:
    return RuleExecutionResult(rule_id=rule.rule_id, status="passed", execution_method="script")


def _not_applicable(rule: LibraryRule, summary: str = "规则不适用于当前材料") -> RuleExecutionResult:
    return RuleExecutionResult(
        rule_id=rule.rule_id,
        status="not_applicable",
        execution_method="script",
        summary=summary,
    )


def _target_check(
    rule: LibraryRule,
    target: dict[str, Any],
    index: MaterialIndex,
    trigger: dict[str, Any] | None = None,
) -> RuleExecutionResult:
    field = str(target.get("field") or rule.field_path or rule.table_name)
    operator = str(target.get("op") or "required")
    matches = index.values(field, labels=rule.applicable_materials)
    if not matches:
        matches = [("", field, "")]
    relevant = [item for item in matches if not trigger or _condition_satisfied(trigger, index, item[1])]
    if not relevant:
        return _not_applicable(rule, "触发条件未满足")
    violations: list[tuple[str, str, str]] = []
    evaluated_count = 0
    for value, location, material_name in relevant:
        if operator == "required":
            evaluated_count += 1
            if _blank(value):
                violations.append((value, location, material_name))
        elif operator in {
            "equals",
            "not_equals",
            "contains",
            "not_contains",
            "in",
            "contains_any",
            "contains_all",
            "not_contains_all",
            "blank",
            "not_blank",
        }:
            if operator not in {"blank", "not_blank"} and _blank(value):
                continue
            evaluated_count += 1
            if not _match(value, operator, expected=target.get("value"), values=target.get("values")):
                violations.append((value, location, material_name))
        elif operator in {"lte_field", "gte_field"}:
            if _blank(value):
                continue
            other_field = str(target.get("other_field") or target.get("right_field") or "")
            other_matches = index.values(other_field, target_location=location)
            if not other_matches or _blank(other_matches[0][0]):
                continue
            evaluated_count += 1
            left = _decimal(value)
            right = _decimal(other_matches[0][0]) if other_matches else None
            if left is None or right is None:
                raise NeedsAIFallback(f"字段比较缺少有效数值：{field}/{other_field}")
            if (operator == "lte_field" and left > right) or (operator == "gte_field" and left < right):
                violations.append((f"{value}; 对比值:{right}", location, material_name))
        elif operator == "range":
            if _blank(value):
                continue
            evaluated_count += 1
            number = _decimal(value)
            if number is None:
                violations.append((value, location, material_name))
                continue
            if target.get("min") is not None and number < Decimal(str(target["min"])):
                violations.append((value, location, material_name))
            if target.get("max") is not None and number > Decimal(str(target["max"])):
                violations.append((value, location, material_name))
        else:
            raise NeedsAIFallback(f"不支持的目标操作符：{operator}")
    if evaluated_count == 0:
        return _not_applicable(rule, "目标字段为空，值域或格式校验不适用")
    return (
        _failed(rule, f"{field.split('.')[-1]}不满足规则要求", _evidence(violations, field))
        if violations
        else _passed(rule)
    )


def _execute_basic(rule: LibraryRule, index: MaterialIndex) -> RuleExecutionResult:
    operator = rule.operator
    params = rule.script_params or {}
    field = rule.field_path or rule.table_name or rule.rule_name
    labels = rule.applicable_materials
    matches = index.values(field, labels=labels)

    if operator == "material_required":
        label = str(params.get("material_label") or (labels[0] if labels else rule.rule_name))
        materials = index.materials_matching(label)
        extensions = [str(item).lower().lstrip(".") for item in params.get("file_ext") or []]
        if materials and extensions:
            materials = [
                material
                for material in materials
                if any(material.material_name.lower().endswith(f".{extension}") for extension in extensions)
            ]
        return _passed(rule) if materials else _failed(rule, f"未提交{label}", [RuleEvidence(location=label, value=f"缺失:{label}")])

    if operator == "conditional_material_required":
        trigger = params.get("trigger") if isinstance(params.get("trigger"), dict) else {}
        if trigger and not _condition_satisfied(trigger, index):
            return _not_applicable(rule, "材料提交条件未触发")
        label = str(params.get("material_label") or (labels[0] if labels else rule.rule_name))
        return _passed(rule) if index.materials_matching(label) else _failed(rule, f"未提交{label}", [RuleEvidence(location=label, value=f"缺失:{label}")])

    if operator == "conditional_compare":
        trigger = params.get("trigger") if isinstance(params.get("trigger"), dict) else {}
        target = params.get("target") if isinstance(params.get("target"), dict) else {}
        if not target:
            raise NeedsAIFallback("conditional_compare缺少target")
        return _target_check(rule, target, index, trigger)

    if operator == "cross_template_equal":
        current_field = str(params.get("current_field") or field)
        baseline_field = str(params.get("baseline_field") or current_field)
        current = index.values(current_field, labels=labels)
        baseline = index.values(baseline_field, material_type="上一次登记申报模板")
        current = [item for item in current if not _blank(item[0])]
        baseline = [item for item in baseline if not _blank(item[0])]
        if not current or not baseline:
            return _not_applicable(rule, "当前值或历史登记值为空，一致性校验不适用")
        baseline_value = str(baseline[0][0]).strip()
        violations = [item for item in current if str(item[0]).strip() != baseline_value]
        return _failed(rule, f"{field.split('.')[-1]}与历史登记不一致", _evidence(violations)) if violations else _passed(rule)

    if operator == "dependent_enum":
        parent_field = str(params.get("parent_field") or "")
        child_field = str(params.get("child_field") or field)
        mapping = params.get("mapping")
        if not parent_field or not isinstance(mapping, dict) or not mapping:
            raise NeedsAIFallback("dependent_enum参数不完整")
        child_matches = index.values(child_field, labels=labels)
        child_matches = [item for item in child_matches if not _blank(item[0])]
        if not child_matches:
            return _not_applicable(rule, "联动子字段为空，枚举校验不适用")
        violations = []
        for child_value, child_location, material_name in child_matches:
            parent_matches = index.values(parent_field, target_location=child_location)
            if not parent_matches:
                raise NeedsAIFallback("联动枚举缺少父字段")
            allowed = [str(item) for item in mapping.get(str(parent_matches[0][0]).strip(), [])]
            if not allowed:
                raise NeedsAIFallback(f"联动枚举缺少父值映射：{parent_matches[0][0]}")
            if str(child_value).strip() not in allowed:
                violations.append((child_value, child_location, material_name))
        return _failed(rule, f"{child_field.split('.')[-1]}与父字段映射不一致", _evidence(violations)) if violations else _passed(rule)

    if operator == "required":
        if rule.rule_object == "表":
            present = any(_field_matches(location, rule.table_name) or _normalize_field(location).startswith(_normalize_field(rule.table_name)) for _, location, _ in index.entries)
            return _passed(rule) if present else _failed(rule, f"{rule.table_name}未填写", [RuleEvidence(location=rule.table_name, value=f"缺失:{rule.table_name}")])
        return _passed(rule) if matches and all(not _blank(item[0]) for item in matches) else _failed(rule, f"{field.split('.')[-1]}为必填项但未填写", _evidence([item for item in matches if _blank(item[0])], field))

    if not matches:
        return _not_applicable(rule, "目标字段不存在或为空")

    if operator == "enum":
        allowed = [str(item).strip() for item in params.get("values") or []]
        if not allowed:
            raise NeedsAIFallback("enum缺少values")
        present_matches = [item for item in matches if not _blank(item[0])]
        if not present_matches:
            return _not_applicable(rule, "目标字段为空，枚举校验不适用")
        multi = params.get("multi_select") is True or params.get("selection_mode") == "multiple"
        violations = []
        for item in present_matches:
            selected = _split_multi(item[0]) if multi else [str(item[0]).strip()]
            if any(value not in allowed for value in selected):
                violations.append(item)
        return _failed(rule, f"{field.split('.')[-1]}不在允许枚举范围内", _evidence(violations)) if violations else _passed(rule)

    if operator == "max_length":
        maximum = params.get("max_length")
        if not isinstance(maximum, int):
            raise NeedsAIFallback("max_length缺少整数参数")
        present_matches = [item for item in matches if not _blank(item[0])]
        if not present_matches:
            return _not_applicable(rule, "目标字段为空，长度校验不适用")
        violations = [item for item in present_matches if len(str(item[0])) > maximum]
        return _failed(rule, f"{field.split('.')[-1]}长度超过{maximum}个字符", _evidence(violations)) if violations else _passed(rule)

    if operator == "number_precision":
        scale = params.get("scale", 2)
        if not isinstance(scale, int):
            raise NeedsAIFallback("number_precision的scale无效")
        present_matches = [item for item in matches if not _blank(item[0])]
        if not present_matches:
            return _not_applicable(rule, "目标字段为空，数值格式校验不适用")
        violations = []
        for item in present_matches:
            number = _decimal(item[0])
            if number is None or max(0, -number.as_tuple().exponent) > scale:
                violations.append(item)
        return _failed(rule, f"{field.split('.')[-1]}不是有效数值或小数位超过{scale}位", _evidence(violations)) if violations else _passed(rule)

    if operator == "date_format":
        present_matches = [item for item in matches if not _blank(item[0])]
        if not present_matches:
            return _not_applicable(rule, "目标字段为空，日期格式校验不适用")
        violations = [item for item in present_matches if _date(item[0]) is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(item[0]).strip())]
        return _failed(rule, f"{field.split('.')[-1]}日期格式不符合YYYY-MM-DD", _evidence(violations)) if violations else _passed(rule)

    if operator == "date_range":
        today = date.today()
        present_matches = [item for item in matches if not _blank(item[0])]
        if not present_matches:
            return _not_applicable(rule, "目标字段为空，日期范围校验不适用")
        violations = []
        for item in present_matches:
            actual = _date(item[0])
            if actual is None:
                violations.append(item)
                continue
            if params.get("min") == "today" and actual < today:
                violations.append(item)
            if isinstance(params.get("max_days"), int) and (actual - today).days > params["max_days"]:
                violations.append(item)
        return _failed(rule, f"{field.split('.')[-1]}不在允许日期范围内", _evidence(violations)) if violations else _passed(rule)

    if operator == "regex_match":
        pattern = str(params.get("pattern") or "")
        if not pattern:
            raise NeedsAIFallback("regex_match缺少pattern")
        try:
            compiled = re.compile(pattern)
        except re.error as error:
            raise NeedsAIFallback(f"无效正则：{error}") from error
        present_matches = [item for item in matches if not _blank(item[0])]
        if not present_matches:
            return _not_applicable(rule, "目标字段为空，正则格式校验不适用")
        violations = [item for item in present_matches if not compiled.fullmatch(str(item[0]).strip())]
        return _failed(rule, f"{field.split('.')[-1]}不符合格式要求", _evidence(violations)) if violations else _passed(rule)

    if operator == "sequence_contiguous":
        start = int(params.get("start", 1))
        present_matches = [item for item in matches if not _blank(item[0])]
        if not present_matches:
            return _not_applicable(rule, "目标字段为空，序号校验不适用")
        try:
            numbers = [int(str(item[0]).strip()) for item in present_matches]
        except ValueError as error:
            raise NeedsAIFallback("序号包含非整数") from error
        expected = list(range(start, start + len(numbers)))
        return _failed(rule, f"{field.split('.')[-1]}应为连续自然数", _evidence(present_matches)) if sorted(numbers) != expected else _passed(rule)

    if operator == "compare_fields":
        right_field = str(params.get("right_field") or "")
        if not right_field:
            raise NeedsAIFallback("compare_fields缺少right_field")
        relation = str(params.get("relation") or "lte")
        violations = []
        compared_count = 0
        for item in (entry for entry in matches if not _blank(entry[0])):
            right_matches = index.values(right_field, target_location=item[1])
            if not right_matches or _blank(right_matches[0][0]):
                continue
            compared_count += 1
            left = _decimal(item[0])
            right = _decimal(right_matches[0][0]) if right_matches else None
            if left is None or right is None:
                raise NeedsAIFallback("compare_fields缺少可比较数值")
            ok = {"lte": left <= right, "gte": left >= right, "eq": left == right}.get(relation)
            if ok is None:
                raise NeedsAIFallback(f"compare_fields不支持relation={relation}")
            if not ok:
                violations.append(item)
        if compared_count == 0:
            return _not_applicable(rule, "比较字段为空，字段关系校验不适用")
        return _failed(rule, f"{field.split('.')[-1]}与{right_field.split('.')[-1]}关系不符合要求", _evidence(violations)) if violations else _passed(rule)

    if operator == "unique":
        fields = [str(item) for item in params.get("fields") or [field]]
        keys: dict[tuple[str, ...], list[tuple[str, str, str]]] = defaultdict(list)
        primary_matches = index.values(fields[0], labels=labels)
        for item in primary_matches:
            values = [str(item[0]).strip()]
            for other_field in fields[1:]:
                other = index.values(other_field, target_location=item[1])
                values.append(str(other[0][0]).strip() if other else "")
            if params.get("ignore_blank", True) and all(_blank(value) for value in values):
                continue
            keys[tuple(values)].append(item)
        duplicates = [item for items in keys.values() if len(items) > 1 for item in items]
        return _failed(rule, f"{'、'.join(fields)}存在重复值", _evidence(duplicates)) if duplicates else _passed(rule)

    if operator == "reference_exists":
        reference_values = params.get("reference_values")
        if not isinstance(reference_values, list):
            raise NeedsAIFallback("缺少外部参照数据")
        allowed = {str(item).strip() for item in reference_values}
        present_matches = [item for item in matches if not _blank(item[0])]
        if not present_matches:
            return _not_applicable(rule, "目标字段为空，参照数据校验不适用")
        violations = [item for item in present_matches if str(item[0]).strip() not in allowed]
        return _failed(rule, f"{field.split('.')[-1]}不存在于参照数据中", _evidence(violations)) if violations else _passed(rule)

    if operator == "formula_compare":
        return _formula_compare(rule, index)

    if operator == "group_consistency":
        group_field = str(params.get("group_by") or "")
        consistent_fields = [str(item) for item in params.get("consistent_fields") or []]
        if not group_field or not consistent_fields:
            raise NeedsAIFallback("group_consistency参数不完整")
        groups: dict[str, list[str]] = defaultdict(list)
        records: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for group_value, location, material_name in index.values(group_field, labels=labels):
            scope = _array_scope(location)
            values = []
            for consistent_field in consistent_fields:
                field_matches = index.values(consistent_field, target_location=location)
                values.append(str(field_matches[0][0]).strip() if field_matches else "")
            groups[str(group_value).strip()].append("|".join(values))
            records[str(group_value).strip()].append(("|".join(values), scope or location, material_name))
        violations = [item for key, signatures in groups.items() if len(set(signatures)) > 1 for item in records[key]]
        return _failed(rule, f"{group_field}分组内字段不一致", _evidence(violations)) if violations else _passed(rule)

    if operator == "compound_condition":
        return _compound_condition(rule, index)

    raise NeedsAIFallback(f"operator未实现：{operator}")


def _safe_arithmetic(expression: str, index: MaterialIndex) -> Decimal:
    parts = [part.strip() for part in re.split(r"([+\-*/])", expression) if part.strip()]
    rendered: list[str] = []
    for part in parts:
        if part in {"+", "-", "*", "/"}:
            rendered.append(part)
            continue
        number = _decimal(part)
        if number is None:
            matches = index.values(part)
            number = _decimal(matches[0][0]) if matches else None
        if number is None:
            raise NeedsAIFallback(f"公式字段缺少有效数值：{part}")
        rendered.append(str(number))
    parsed = ast.parse(" ".join(rendered), mode="eval")
    allowed_nodes = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.Constant)
    if any(not isinstance(node, allowed_nodes) for node in ast.walk(parsed)):
        raise NeedsAIFallback("公式包含非白名单表达式")

    def evaluate(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant):
            return Decimal(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -evaluate(node.operand)
        if isinstance(node, ast.BinOp):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        raise NeedsAIFallback("公式表达式无法计算")

    return evaluate(parsed)


def _function_formula(expression: str, index: MaterialIndex) -> Decimal | None:
    match = re.fullmatch(r"(business_days_between|months_between)\((.+),(.+)\)", expression.strip())
    if not match:
        return None
    function_name, left_field, right_field = match.groups()
    left_matches = index.values(left_field.strip())
    right_matches = index.values(right_field.strip())
    left_date = _date(left_matches[0][0]) if left_matches else None
    right_date = _date(right_matches[0][0]) if right_matches else None
    if left_date is None or right_date is None:
        raise NeedsAIFallback("公式日期字段缺失或格式无效")
    if function_name == "months_between":
        months = (right_date.year - left_date.year) * 12 + right_date.month - left_date.month
        return Decimal(months)
    direction = 1 if right_date >= left_date else -1
    current = left_date
    days = 0
    while current != right_date:
        current = date.fromordinal(current.toordinal() + direction)
        if current.weekday() < 5:
            days += direction
    return Decimal(days)


def _formula_compare(rule: LibraryRule, index: MaterialIndex) -> RuleExecutionResult:
    params = rule.script_params or {}
    expression = str(params.get("expression") or "")
    if not expression:
        raise NeedsAIFallback("formula_compare缺少expression")
    actual = _function_formula(expression, index)
    if actual is None:
        actual = _safe_arithmetic(expression, index)
    relation = str(params.get("relation") or "equals")
    expected_field = str(params.get("expected_field") or "")
    if relation == "range":
        minimum = Decimal(str(params.get("min", "-Infinity")))
        maximum_value = params.get("max")
        maximum_exclusive = params.get("max_exclusive")
        ok = actual >= minimum
        if maximum_value is not None:
            ok = ok and actual <= Decimal(str(maximum_value))
        if maximum_exclusive is not None:
            ok = ok and actual < Decimal(str(maximum_exclusive))
    else:
        if expected_field:
            expected_matches = index.values(expected_field)
            expected = _decimal(expected_matches[0][0]) if expected_matches else None
        else:
            expected = _decimal(params.get("expected_value"))
        if expected is None:
            raise NeedsAIFallback("formula_compare缺少目标值")
        tolerance = Decimal(str(params.get("tolerance", 0)))
        if relation in {"equals", "within_tolerance"}:
            ok = abs(actual - expected) <= tolerance
        elif relation == "lte":
            ok = actual <= expected
        elif relation == "gte":
            ok = actual >= expected
        else:
            raise NeedsAIFallback(f"不支持公式关系：{relation}")
    return _passed(rule) if ok else _failed(rule, "公式计算结果不符合规则要求", [RuleEvidence(location=expected_field or expression, value=str(actual))])


def _compound_check(rule: LibraryRule, check: dict[str, Any], index: MaterialIndex) -> RuleExecutionResult:
    check_type = str(check.get("type") or "")
    if check_type == "conditional_compare":
        return _target_check(rule, check.get("target") or {}, index, check.get("trigger") or {}) if not check.get("unless") or not _condition_satisfied(check["unless"], index) else _not_applicable(rule)
    if check_type == "conditional_enum":
        if not _condition_satisfied(check.get("trigger") or {}, index):
            return _not_applicable(rule)
        target_config = {"field": check.get("field"), "op": "in", "values": check.get("values") or []}
        if check.get("required"):
            required_result = _target_check(rule, {"field": check.get("field"), "op": "required"}, index)
            if required_result.status == "failed":
                return required_result
        return _target_check(rule, target_config, index)
    if check_type == "dependent_enum":
        if check.get("trigger") and not _condition_satisfied(check["trigger"], index):
            return _not_applicable(rule)
        temporary = rule.model_copy(update={"operator": "dependent_enum", "script_params": check})
        return _execute_basic(temporary, index)
    if check_type == "numeric_range":
        return _target_check(rule, {"field": check.get("field"), "op": "range", "min": check.get("min"), "max": check.get("max")}, index)
    if check_type == "field_compare":
        mapping = {"lte": "lte_field", "gte": "gte_field"}
        target_operator = mapping.get(str(check.get("op")))
        if not target_operator:
            raise NeedsAIFallback("compound field_compare操作符不支持")
        return _target_check(rule, {"field": check.get("left_field"), "op": target_operator, "other_field": check.get("right_field")}, index)
    if check_type == "date_compare":
        left_field = str(check.get("left_field") or "")
        right_field = str(check.get("right_field") or "")
        relation = str(check.get("op") or "")
        left_matches = index.values(left_field)
        if not left_matches:
            raise NeedsAIFallback("日期比较缺少左侧字段")
        violations = []
        for item in left_matches:
            right_matches = index.values(right_field, target_location=item[1])
            left_date = _date(item[0])
            right_date = _date(right_matches[0][0]) if right_matches else None
            if left_date is None or right_date is None:
                raise NeedsAIFallback("日期比较缺少有效日期")
            ok = {"lte": left_date <= right_date, "gte": left_date >= right_date, "lt": left_date < right_date, "gt": left_date > right_date}.get(relation)
            if ok is None:
                raise NeedsAIFallback("日期比较关系无效")
            if not ok:
                violations.append(item)
        return _failed(rule, f"{left_field}与{right_field}日期关系不符合要求", _evidence(violations)) if violations else _passed(rule)
    if check_type == "enum":
        temporary = rule.model_copy(update={"operator": "enum", "field_path": str(check.get("field") or rule.field_path), "script_params": check})
        return _execute_basic(temporary, index)
    if check_type == "forbidden_combination":
        field = str(check.get("field") or "")
        forbidden = [str(item) for item in check.get("values") or []]
        matches = index.values(field)
        violations = [item for item in matches if all(value in _split_multi(item[0]) for value in forbidden)]
        return _failed(rule, f"{field}包含互斥选项", _evidence(violations)) if violations else _passed(rule)
    if check_type == "conditional_blank":
        if not _condition_satisfied(check.get("trigger") or {}, index):
            return _not_applicable(rule)
        return _target_check(rule, check.get("target") or {}, index)
    if check_type == "file_size_limit":
        label = str(check.get("material_label") or "")
        materials = index.materials_matching(label)
        if not materials and not check.get("required"):
            return _not_applicable(rule)
        if any(material.size_bytes is None for material in materials):
            raise NeedsAIFallback("解析材料未提供文件大小")
        maximum = int(check.get("max_mb", 0)) * 1024 * 1024
        violations = [material for material in materials if int(material.size_bytes or 0) > maximum]
        evidence = [RuleEvidence(material_name=item.material_name, location="文件大小", value=str(item.size_bytes)) for item in violations]
        return _failed(rule, f"{label}超过{check.get('max_mb')}MB", evidence) if violations else _passed(rule)
    if check_type in {"text_format", "numeric_text_format"}:
        violations: list[tuple[str, str, str]] = []
        for _, location, value in index.entries:
            text = str(value or "")
            if check_type == "text_format":
                if check.get("forbid_control_chars") and re.search(r"[\x00-\x1f\x7f]", text):
                    violations.append((text, location, ""))
                if check.get("trim_required") and text != text.strip():
                    violations.append((text, location, ""))
            elif _decimal(text) is not None:
                if check.get("forbid_plus_sign") and text.strip().startswith("+"):
                    violations.append((text, location, ""))
                if check.get("forbid_redundant_leading_zero") and re.fullmatch(r"0\d+", text.strip()):
                    violations.append((text, location, ""))
                if check.get("forbid_redundant_fraction_trailing_zero") and "." in text and text.rstrip("0") != text:
                    violations.append((text, location, ""))
        return _failed(rule, "材料字段格式不符合规则要求", _evidence(violations)) if violations else _passed(rule)
    if check_type == "number_precision":
        temporary = rule.model_copy(update={"operator": "number_precision", "field_path": str(check.get("field") or rule.field_path), "script_params": check})
        return _execute_basic(temporary, index)
    if check_type == "regex_match":
        temporary = rule.model_copy(update={"operator": "regex_match", "field_path": str(check.get("field") or rule.field_path), "script_params": check})
        return _execute_basic(temporary, index)
    if check_type == "max_length":
        temporary = rule.model_copy(update={"operator": "max_length", "field_path": str(check.get("field") or rule.field_path), "script_params": check})
        return _execute_basic(temporary, index)
    raise NeedsAIFallback(f"compound_condition子类型未实现：{check_type}")


def _compound_condition(rule: LibraryRule, index: MaterialIndex) -> RuleExecutionResult:
    conditions = rule.script_params.get("conditions") if isinstance(rule.script_params, dict) else None
    if not isinstance(conditions, list) or not conditions:
        raise NeedsAIFallback("compound_condition缺少conditions")
    results = [_compound_check(rule, condition, index) for condition in conditions if isinstance(condition, dict)]
    failed_results = [result for result in results if result.status == "failed"]
    if failed_results:
        evidence = [item for result in failed_results for item in result.evidence]
        summaries = "；".join(dict.fromkeys(result.summary for result in failed_results if result.summary))
        return _failed(rule, summaries or "多条件组合校验失败", evidence)
    if results and all(result.status == "not_applicable" for result in results):
        return _not_applicable(rule)
    return _passed(rule)


def execute_rule(rule: LibraryRule, materials: list[ExtractedMaterial]) -> RuleExecutionResult | None:
    start = time.perf_counter()
    if rule.operator not in SUPPORTED_OPERATORS:
        raise NeedsAIFallback(f"operator未注册：{rule.operator}")
    result = _execute_basic(rule, MaterialIndex(materials))
    result.duration_seconds = round(time.perf_counter() - start, 6)
    return result


def execute_rules(
    rules: list[LibraryRule],
    materials: list[ExtractedMaterial],
) -> tuple[list[RuleExecutionResult], list[LibraryRule]]:
    results: list[RuleExecutionResult] = []
    fallback: list[LibraryRule] = []
    for rule in rules:
        try:
            result = execute_rule(rule, materials)
            if result is not None:
                results.append(result)
        except Exception:
            fallback.append(rule)
    return results, fallback
