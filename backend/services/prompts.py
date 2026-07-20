from __future__ import annotations

import json

from ..models.schemas import ExtractedMaterial
from .rule_library import LibraryProcess, LibraryRule, PROCESS_LABELS


PROMPT_VERSION = "rule-engine-v1.0"

FLOW_PROMPTS = {
    "pre_registration": "你是信托产品预登记审核助手，只依据给定规则和材料判断。",
    "pre_report": "你是信托产品事前报告审核助手，只依据给定规则和材料判断。",
    "initial": "你是信托产品初始登记审核助手，只依据给定规则和材料判断。",
    "termination": "你是信托产品终止登记审核助手，只依据给定规则和材料判断。",
}

DIMENSION_PROMPTS = {
    "文件格式标准化": "重点核验格式、长度、数据类型、枚举、日期和文件要求。",
    "法定要素完整性": "重点核验必填字段、条件性必填字段和法定材料是否完整。",
    "文本语义合规": "重点核验材料表述是否符合正式规则，不得扩张解释。",
    "跨文件数据一致性": "逐项比对不同材料或表格中的同一事实，并引用双方证据。",
    "非标资产穿透": "重点核验底层资产、交易对手和穿透信息是否完整一致。",
    "报送时效合规": "重点核验日期关系、工作日期限和报送时点。",
}


def build_messages(
    process: LibraryProcess,
    dimension: str,
    rules: list[LibraryRule],
    materials: list[ExtractedMaterial],
    execution_method: str,
) -> list[dict[str, str]]:
    flow = FLOW_PROMPTS[process]
    dimension_prompt = DIMENSION_PROMPTS.get(dimension, "严格按给定规则逐条判断。")
    fallback = ""
    if execution_method == "ai_fallback":
        fallback = (
            "这些规则原计划由脚本执行，但因参数、外部数据或运行条件不足转为AI兜底。"
            "不得把脚本不可执行本身判定为材料问题；证据不足时返回undetermined。"
        )
    system = f"""{flow}
当前流程：{PROCESS_LABELS[process]}。当前审核维度：{dimension}。
{dimension_prompt}
{fallback}
必须为批内每条规则返回且仅返回一条结果，不能遗漏、重复或增加rule_id。
允许状态只有passed、failed、not_applicable、undetermined。
材料片段的location和text是规则引擎标准化后的中文审核路径和值；raw_location和raw_text仅用于追溯原始申报代码，不得优先于标准化值。
只有存在明确材料证据时才能返回failed；failed必须给出问题摘要、整改建议和真实证据位置。
材料缺失或证据不足且无法完成判断时返回undetermined；规则触发条件未满足时返回not_applicable。
不要输出Markdown。输出合法JSON：
{{"results":[{{"rule_id":"...","status":"passed|failed|not_applicable|undetermined","summary":"","suggestion":"","evidence":[{{"material_name":"","location":"","value":""}}]}}]}}
"""
    rule_payload = [
        {
            "rule_id": rule.rule_id,
            "rule_name": rule.rule_name,
            "review_dimension": rule.review_dimension,
            "applicable_materials": rule.applicable_materials,
            "field_path": rule.field_path,
            "trigger_condition": rule.trigger_condition,
            "rule_text": rule.rule_text,
            "basis_text": rule.basis_text,
            "special_prompt": rule.special_prompt,
            "script_operator": rule.operator if execution_method == "ai_fallback" else "",
            "script_params": rule.script_params if execution_method == "ai_fallback" else {},
        }
        for rule in rules
    ]
    material_payload = [material.model_dump() for material in materials]
    user = json.dumps(
        {"rules": rule_payload, "materials": material_payload},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
