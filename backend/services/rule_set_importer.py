"""规则版本 Excel 导入。

读取导入版 Excel 的「脚本审核规则」「AI审核规则」两个 sheet，
转换为现有 review_service 使用的 Rule 结构。
"""
from __future__ import annotations

import io
import json
from typing import Any

from openpyxl import load_workbook

from .schemas import PROCESS_LABEL, ProcessType, Rule


SCRIPT_SHEET = "脚本审核规则"
AI_SHEET = "AI审核规则"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _headers(ws) -> dict[str, int]:
    return {_text(cell.value): idx for idx, cell in enumerate(ws[1]) if _text(cell.value)}


def _cell(row: tuple[Any, ...], mapping: dict[str, int], key: str) -> str:
    idx = mapping.get(key)
    if idx is None or idx >= len(row):
        return ""
    return _text(row[idx])


def _split(value: str) -> list[str]:
    if not value:
        return []
    import re

    return [p.strip() for p in re.split(r"[、,，;；/\n]+", value) if p.strip()]


def _risk(value: str) -> str:
    if "高" in value:
        return "高风险"
    if "低" in value:
        return "低风险"
    return "中风险"


def _parse_params(raw: str, errors: list[dict], *, sheet: str, row_no: int, rule_id: str) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        errors.append(
            {
                "sheet": sheet,
                "row": row_no,
                "rule_id": rule_id,
                "message": f"参数(JSON)解析失败：{e}",
            }
        )
        return {}
    if not isinstance(parsed, dict):
        errors.append(
            {
                "sheet": sheet,
                "row": row_no,
                "rule_id": rule_id,
                "message": "参数(JSON)必须是对象",
            }
        )
        return {}
    return parsed


def _normalize_dimension(value: str) -> str:
    mapping = {
        "格式模板": "格式模板规则库",
        "登记必填要素": "登记必填要素规则库",
        "跨材料数据逻辑": "跨材料数据逻辑校验库",
        "监管合规红线": "监管合规红线规则库",
        "业务退回/整改": "业务退回/整改案例库",
        "审查风险分级": "审查风险分级规则库",
    }
    return mapping.get(value, value or "其他")


def _script_rule_needs_configuration(rule: Rule) -> bool:
    if rule.review_method != "script":
        return False
    if rule.operator in {"custom_condition", "format_check"}:
        return True
    if rule.operator != "conditional_compare":
        return False
    params = rule.script_params or {}
    if params.get("external_source_required"):
        return True
    target = params.get("target")
    return not isinstance(target, dict) or not target.get("field") or not target.get("op")


def script_rule_needs_configuration(rule: Rule) -> bool:
    """Public helper used by review flow for AI fallback."""
    return _script_rule_needs_configuration(rule)


def _rule_common(
    *,
    process: ProcessType,
    filename: str,
    row: tuple[Any, ...],
    mapping: dict[str, int],
    sheet: str,
    row_no: int,
    review_method: str,
    errors: list[dict],
) -> Rule | None:
    rule_id = _cell(row, mapping, "规则ID")
    rule_text = _cell(row, mapping, "具体规则")
    if not rule_id:
        errors.append({"sheet": sheet, "row": row_no, "message": "缺少规则ID"})
        return None
    if not rule_text:
        errors.append({"sheet": sheet, "row": row_no, "rule_id": rule_id, "message": "缺少具体规则"})
        return None

    field_path = _cell(row, mapping, "字段路径")
    section = _cell(row, mapping, "要素分类/表名")
    field_name = _cell(row, mapping, "规则名称/要素名")
    if "." in field_path:
        section, field_name = field_path.rsplit(".", 1)
    elif field_path:
        field_name = field_path

    source_sheet = _cell(row, mapping, "来源sheet") or sheet
    source_row_raw = _cell(row, mapping, "来源行")
    try:
        source_row = int(source_row_raw) if source_row_raw else row_no
    except ValueError:
        source_row = row_no

    operator = _cell(row, mapping, "operator")
    params = _parse_params(
        _cell(row, mapping, "参数(JSON)"),
        errors,
        sheet=sheet,
        row_no=row_no,
        rule_id=rule_id,
    )
    if review_method == "script" and not operator:
        errors.append({"sheet": sheet, "row": row_no, "rule_id": rule_id, "message": "脚本规则缺少operator"})

    return Rule(
        rule_id=rule_id,
        registration_type=PROCESS_LABEL.get(process, process),
        rule_source="上传规则",
        source_file=filename,
        source_sheet=source_sheet,
        source_row=source_row,
        rule_name=_cell(row, mapping, "规则名称/要素名") or rule_id,
        rule_text=rule_text,
        basis_file=_cell(row, mapping, "审查依据") or filename,
        basis_text=_cell(row, mapping, "审查依据"),
        review_dimension=_normalize_dimension(_cell(row, mapping, "审查维度")),
        table_name=section,
        field_name=field_name,
        applicable_materials=_split(_cell(row, mapping, "适用材料")),
        review_method=review_method,
        rule_object=_cell(row, mapping, "规则对象"),
        operator=operator,
        script_params=params,
        check_type=_cell(row, mapping, "比对方式") or _cell(row, mapping, "AI审核重点") or operator or "语义条件判断",
        trigger_condition=_cell(row, mapping, "触发条件"),
        machine_params=json.dumps({"operator": operator, "params": params}, ensure_ascii=False) if operator else "",
        risk_level=_risk(_cell(row, mapping, "风险等级")),
        ai_check_focus=[_cell(row, mapping, "AI审核重点")] if _cell(row, mapping, "AI审核重点") else [],
        evidence_requirement="请指出涉及的材料、表名、字段、页码或文本片段。",
        rule_role="uploaded_script" if review_method == "script" else "uploaded_ai",
        severity_type="issue",
        issue_type=_cell(row, mapping, "规则对象") or "",
        field_anchor=field_path or field_name,
        enabled=_cell(row, mapping, "启用状态") not in {"否", "false", "False", "0"},
        demo_enabled=True,
    )


def import_rule_set_from_excel(content: bytes, *, filename: str, process: ProcessType) -> tuple[list[Rule], dict]:
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    rules: list[Rule] = []
    errors: list[dict] = []
    warnings: list[dict] = []
    try:
        missing = [name for name in (SCRIPT_SHEET, AI_SHEET) if name not in wb.sheetnames]
        if missing:
            raise ValueError(f"缺少必要sheet：{', '.join(missing)}")

        for sheet, method in ((SCRIPT_SHEET, "script"), (AI_SHEET, "ai")):
            ws = wb[sheet]
            mapping = _headers(ws)
            for required in ("规则ID", "具体规则"):
                if required not in mapping:
                    raise ValueError(f"{sheet} 缺少必要列：{required}")
            if method == "script" and "operator" not in mapping:
                raise ValueError(f"{sheet} 缺少必要列：operator")

            for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                if not any(_text(v) for v in row):
                    continue
                rule = _rule_common(
                    process=process,
                    filename=filename,
                    row=row,
                    mapping=mapping,
                    sheet=sheet,
                    row_no=row_no,
                    review_method=method,
                    errors=errors,
                )
                if rule is None:
                    continue
                if _script_rule_needs_configuration(rule):
                    warnings.append(
                        {
                            "sheet": sheet,
                            "row": row_no,
                            "rule_id": rule.rule_id,
                            "message": f"{rule.operator} 暂按保守策略入库，参数不足时审核阶段跳过",
                        }
                    )
                rules.append(rule)
    finally:
        wb.close()

    seen: set[str] = set()
    duplicates = []
    for r in rules:
        if r.rule_id in seen:
            duplicates.append(r.rule_id)
        seen.add(r.rule_id)
    if duplicates:
        raise ValueError(f"规则ID重复：{', '.join(sorted(set(duplicates)))}")

    report = {
        "total_rules": len(rules),
        "script_count": sum(1 for r in rules if r.review_method == "script"),
        "ai_count": sum(1 for r in rules if r.review_method == "ai"),
        "unsupported_count": sum(1 for r in rules if _script_rule_needs_configuration(r)),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }
    if errors:
        first = errors[0]
        raise ValueError(
            f"{len(errors)} 条规则解析错误，首条：{first.get('sheet', '')} 第{first.get('row', '')}行 {first.get('message', '')}"
        )
    return rules, report
