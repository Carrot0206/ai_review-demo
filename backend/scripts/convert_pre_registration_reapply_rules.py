from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[3]
SOURCE_CANDIDATES = [
    ROOT / "重新申请预登记文件审查规则表.xlsx",
]
SOURCE = next((p for p in SOURCE_CANDIDATES if p.exists()), SOURCE_CANDIDATES[0])
PRE_REG_RULES = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "rules"
    / "rules_pre_registration.json"
)
OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "rules"
    / "rules_pre_registration_reapply.json"
)


def clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_dimension(value: str) -> str:
    raw = clean(value)
    if not raw:
        return "其他"
    if raw.endswith("规则库") or raw.endswith("案例库"):
        return raw
    mapping = {
        "格式模板": "格式模板规则库",
        "登记必填要素": "登记必填要素规则库",
        "跨材料数据逻辑": "跨材料数据逻辑校验库",
        "监管合规红线": "监管合规红线规则库",
        "业务退回/整改": "业务退回/整改案例库",
        "审查风险分级": "审查风险分级规则库",
    }
    return mapping.get(raw, raw)


def risk_level(rule_text: str, dimension: str) -> str:
    text = rule_text or ""
    if any(kw in text for kw in ("缺失", "未提交", "需提交", "需上传", "应提交", "应上传", "必须", "不一致")):
        return "高风险"
    if "监管合规" in dimension or "跨材料" in dimension:
        return "中风险"
    return "中风险"


def severity_type(dimension: str) -> str:
    return "risk_hint" if "审查风险分级" in dimension else "issue"


def issue_type(rule_name: str, rule_text: str, dimension: str) -> str:
    text = f"{rule_name} {rule_text}"
    if "审查风险分级" in dimension:
        return "风险提示"
    if any(kw in text for kw in ("提交", "上传", "提供", "材料")):
        return "材料必交"
    if "一致" in text:
        return "跨材料一致性"
    if "监管合规" in dimension or "合规" in text:
        return "监管红线"
    return "文件审查"


def check_type(rule_name: str, rule_text: str, dimension: str) -> str:
    text = f"{rule_name} {rule_text}"
    if "一致" in text or "相同" in text:
        return "跨材料一致性"
    if any(kw in text for kw in ("提交", "上传", "提供", "材料")):
        return "材料完整性"
    if "监管" in dimension or "合规" in text:
        return "监管口径符合性"
    return "语义条件判断"


def file_applicable_materials(file_name: str, rule_name: str, rule_text: str) -> list[str]:
    text = f"{file_name} {rule_name} {rule_text}"
    materials: list[str] = []
    if "申请书" in text:
        materials.append("信托预登记申请书")
    if "模板" in text or "JSON" in text or "json" in text:
        materials.append("预登记产品EXCEL模板.json")
    if "要素报告表" in text:
        materials.append("信托预登记要素报告表")
    if "政信" in text or "融资平台债务" in text:
        materials.append("政信类证明材料")
    if "新型资产服务信托" in text or "情况说明" in text:
        materials.append("新型资产服务信托情况说明")
    if "其他文件" in text or "其他附件" in text:
        materials.append("其他附件")
    if not materials:
        materials = ["信托预登记申请书", "预登记产品EXCEL模板.json", "其他附件"]
    return list(dict.fromkeys(materials))


def rule_role(rule_name: str, rule_text: str, dimension: str) -> str:
    itype = issue_type(rule_name, rule_text, dimension)
    return {
        "材料必交": "material_required",
        "跨材料一致性": "cross_document_consistency",
        "监管红线": "regulatory_redline",
        "风险提示": "risk_hint",
    }.get(itype, "file_review")


def apply_file_rule_overrides(item: dict[str, Any]) -> dict[str, Any]:
    """Tighten AI execution semantics for reapply file-review rows."""
    trigger = clean(item.get("trigger_condition", ""))
    rule_name = clean(item.get("rule_name", ""))
    if rule_name == "模板下载" and "预登记产品EXCEL模板" in trigger:
        item["check_type"] = "格式模板检查"
        item["rule_role"] = "template_json_required"
        item["issue_type"] = "格式模板"
        item["ai_check_focus"] = [
            "本网页审核上传材料为预登记Excel模板导出的JSON，不要求上传Excel原文件",
            "检查当前申报模板JSON是否存在、可解析，且预登记类型字段按重新申请预登记口径填写",
            "不得因未上传Excel原文件输出缺失Excel模板问题",
        ]
    if rule_name == "与JSON一致性" and "信托预登记要素报告表PDF" in trigger:
        item["rule_role"] = "cross_document_consistency"
        item["issue_type"] = "跨材料一致性"
        item["skip_when"] = "信托预登记要素报告表PDF缺失"
        item["ai_check_focus"] = [
            "仅在已上传信托预登记要素报告表PDF时检查",
            "核对要素报告表PDF是否由同一申报模板JSON形成",
            "未上传要素报告表PDF时本规则跳过，不输出缺失问题",
        ]
    return item


def file_review_rules(ws) -> list[dict[str, Any]]:
    headers = [clean(c.value) for c in ws[1]]
    col = {h: i for i, h in enumerate(headers)}
    rules: list[dict[str, Any]] = []
    for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        values = [clean(v) for v in row]
        if not any(values):
            continue
        if values[col.get("分类", -1)] != "ai":
            continue
        file_name = values[col["文件名"]]
        rule_name = values[col["文件审查规则"]]
        dim = normalize_dimension(values[col["审核维度"]])
        rule_text = values[col["具体的规则"]]
        basis = values[col["审核依据"]]
        idx = len(rules) + 1
        rid = f"REREG-FILE-AI-{idx:03d}"
        item = {
            "rule_id": rid,
            "registration_type": "重新申请预登记",
            "rule_source": "内置规则",
            "source_file": SOURCE.name,
            "source_sheet": ws.title,
            "source_row": row_no,
            "rule_name": rule_name or file_name or "重新申请预登记文件审查",
            "rule_text": rule_text,
            "basis_file": basis.split("“", 1)[0].strip()[:80] if basis else "",
            "basis_text": basis,
            "review_dimension": dim,
            "table_name": "",
            "field_name": "",
            "applicable_materials": file_applicable_materials(file_name, rule_name, rule_text),
            "review_method": "ai",
            "original_review_method": "AI",
            "check_type": check_type(rule_name, rule_text, dim),
            "trigger_condition": file_name,
            "machine_params": "",
            "risk_level": risk_level(rule_text, dim),
            "ai_check_focus": [
                "判断重新申请预登记申请材料是否齐备或一致",
                "指出缺失、不一致或证明不充分的材料名称和位置",
                "流程性前提在未接入系统状态时只作为风险提示，不输出硬性违规",
            ],
            "evidence_requirement": "请 AI 指出涉及的材料、表名、字段、页码或文本片段。",
            "rule_role": rule_role(rule_name, rule_text, dim),
            "severity_type": severity_type(dim),
            "issue_type": issue_type(rule_name, rule_text, dim),
            "field_anchor": "",
            "skip_when": "",
            "enabled": True,
            "demo_enabled": True,
        }
        rules.append(apply_file_rule_overrides(item))
    return rules


def parse_json_list(value: str) -> list[str]:
    raw = clean(value)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
    except json.JSONDecodeError:
        pass
    return [item.strip() for item in re.split(r"[;,，；]", raw) if item.strip()]


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y", "是"}


def has_baseline_guard(rule: dict[str, Any]) -> bool:
    text = " ".join(
        clean(rule.get(k, ""))
        for k in ("machine_params", "skip_when", "trigger_condition", "rule_text", "ai_check_focus")
    )
    return "requires_baseline=true" in text or "baseline_missing" in text


def proprietary_rules(ws) -> list[dict[str, Any]]:
    headers = [clean(c.value) for c in ws[1]]
    rows: list[dict[str, Any]] = []
    for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        raw = {header: clean(row[idx]) if idx < len(row) else "" for idx, header in enumerate(headers)}
        method = raw.get("review_method", "")
        if method not in {"ai", "hybrid"}:
            continue
        if raw.get("enabled", "").lower() in {"false", "0", "否"}:
            continue
        item: dict[str, Any] = {}
        for header in headers:
            value: Any = raw.get(header, "")
            if header in {"applicable_materials", "ai_check_focus"}:
                value = parse_json_list(value)
            elif header in {"enabled", "demo_enabled", "needs_human"}:
                value = parse_bool(value)
            elif header == "source_row":
                try:
                    value = int(value)
                except ValueError:
                    value = row_no
            item[header] = value
        item["source_row"] = int(item.get("source_row") or row_no)
        item.setdefault("rule_source", "内置规则")
        item.setdefault("source_file", SOURCE.name)
        item.setdefault("source_sheet", ws.title)
        item["registration_type"] = "重新申请预登记"
        if item.get("review_method") == "hybrid":
            item["review_method"] = "ai"
            item["original_review_method"] = "混合"
        if "CA认证登录状态" in item.get("skip_when", "") or "系统状态" in item.get("rule_text", ""):
            item["severity_type"] = "risk_hint"
            item["issue_type"] = item.get("issue_type") or "流程性前提提示"
        if "DIFF" in item["rule_id"] or "差异" in item.get("rule_name", "") or "原预登记" in item.get("rule_text", ""):
            params = item.get("machine_params", "")
            if "requires_baseline=true" not in params:
                item["machine_params"] = f"{params}; requires_baseline=true".strip("; ")
            item["skip_when"] = "baseline_missing"
            if not has_baseline_guard(item):
                raise RuntimeError(f"差异规则缺少 baseline guard: {item['rule_id']}")
        rows.append(item)
    return rows


def reusable_pre_registration_rules() -> list[dict[str, Any]]:
    data = json.loads(PRE_REG_RULES.read_text(encoding="utf-8"))
    rules: list[dict[str, Any]] = []
    excluded_reapply_ids = {
        # Reapply has its own file review rules for application materials.
        # These reused standard-opinion element rows are ordinary pre-registration
        # material requirements, not current-template element checks.
        "PREG-ELEMENT-AI-001",  # 请提供登记申请书
        "PREG-ELEMENT-AI-002",  # 请提供合规承诺书
        "PREG-ELEMENT-AI-003",  # 登记申请书缺少填表人签字
        "PREG-ELEMENT-AI-004",  # 合规承诺书缺少公章或分管高管签字
    }
    for raw in data["rules"]:
        rid = clean(raw.get("rule_id"))
        # Reapply has its own file/material rules. Keep the element/semantic rule set.
        if rid.startswith("PREG-FILE-") or rid in excluded_reapply_ids:
            continue
        item = dict(raw)
        item["rule_id"] = f"REREG-{rid}"
        item["registration_type"] = "重新申请预登记"
        item["rule_source"] = item.get("rule_source") or "内置规则"
        item["source_file"] = item.get("source_file") or "rules_pre_registration.json"
        if rid == "PREG-ELEMENT-AI-026":
            item["trigger_condition"] = "当前模板或材料出现资产证券化、资产支持证券、ABS、其他资产证券化信托等业务特征"
            item["machine_params"] = "if no asset_securitization_feature then skip"
            item["skip_when"] = "未识别到资产证券化信托业务特征"
            item["ai_check_focus"] = [
                "先确认当前申报模板或附件是否出现资产证券化、资产支持证券、ABS、其他资产证券化信托等业务特征",
                "仅在确认属于资产证券化相关业务时，检查交易结构简介是否披露资产支持证券及管理人信息",
                "不得把一般资产服务信托或新型资产服务信托直接等同于资产证券化信托",
            ]
        rules.append(item)
    return rules


def main() -> None:
    wb = load_workbook(SOURCE, data_only=True, read_only=True)
    proprietary_sheet = (
        wb["重新申请专属规则"]
        if "重新申请专属规则" in wb.sheetnames
        else wb["重新申请预登记专属规则"]
    )
    rules = (
        reusable_pre_registration_rules()
        + file_review_rules(wb["文件审查规则"])
        + proprietary_rules(proprietary_sheet)
    )
    for rule in rules:
        if "DIFF" in rule.get("rule_id", "") and not has_baseline_guard(rule):
            raise RuntimeError(f"差异规则缺少 baseline guard: {rule['rule_id']}")
        if rule.get("review_method") == "config":
            raise RuntimeError(f"config 规则不得进入输出: {rule['rule_id']}")

    payload = {
        "rule_set_id": "pre_registration_reapply_ai_rules_v1",
        "registration_type": "重新申请预登记",
        "source_file": SOURCE.name,
        "description": "重新申请预登记 AI 审核规则；复用完整预登记要素规则，并追加重新申请文件审查和专属规则。",
        "total_rules": len(rules),
        "rules": rules,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(rules)} rules)")


if __name__ == "__main__":
    main()
