"""Prompt 组装：把规则数组 + 材料片段拼成 DeepSeek 的对话消息。

设计原则：
- system 强约束：只对给定规则判断、未发现问题不输出、必须返回合法 JSON。
- user 给出规则数组（精简字段）+ 材料文本片段（含 location 坐标）。
- 不让模型生成 rule_basis / risk_level —— 后端根据 rule_id 回填。
"""
from __future__ import annotations

import json
from typing import Any

from .schemas import ExtractedMaterial, Rule, PROCESS_LABEL

SYSTEM_PROMPT = """你是中信登（中国信托登记有限责任公司）信托产品登记审核助手。
任务：严格依据用户给定的【审核规则】审查【申请材料】，仅就规则覆盖到的问题进行反馈。

铁律：
1. 只能针对给定规则发现问题；不要超出规则范围去审查。
2. 一条规则可能产生 0 或多个问题；未发现问题时不要输出该规则。
3. 输出必须是合法 JSON，且严格符合下文给定 schema。
4. 在 issue_location 中必须给出真实的材料名 material_name、定位坐标 location（例如 "第2页"、"产品基本信息表.信托业务分类"）、原文/填写值 value，不允许编造材料中不存在的内容。
5. 不要复述规则原文；不要编造来源；不要输出 markdown、注释、解释性文字。
6. issue_summary 用一句话中文总结，不超过 60 字。
7. suggestion 用一句话中文整改建议，不超过 80 字。
8. 不要输出 risk_level、rule_basis 字段（由系统回填）。
"""

OUTPUT_SCHEMA_HINT = """输出 JSON 结构：
{
  "issues": [
    {
      "rule_id": "命中的规则 ID（必须来自下方规则列表的 rule_id）",
      "issue_summary": "一句话总结",
      "issue_location": [
        {"material_name": "...", "location": "...", "value": "..."}
      ],
      "suggestion": "整改建议"
    }
  ]
}
若没有发现任何问题，输出：{"issues": []}
"""


def _rule_to_prompt_obj(rule: Rule) -> dict[str, Any]:
    """精简规则字段送进 prompt，避免 token 浪费。"""
    return {
        "rule_id": rule.rule_id,
        "rule_name": rule.rule_name,
        "rule_text": rule.rule_text,
        "review_dimension": rule.review_dimension,
        "applicable_materials": rule.applicable_materials,
        "check_type": rule.check_type,
        "table_name": rule.table_name,
        "field_name": rule.field_name,
        "trigger_condition": rule.trigger_condition,
        "ai_check_focus": rule.ai_check_focus,
        "evidence_requirement": rule.evidence_requirement,
    }


def _material_to_text(material: ExtractedMaterial, max_chars_per_segment: int = 1500) -> str:
    """把一份材料渲染成纯文本块。"""
    lines = [f"### 材料：{material.material_name}（类型：{material.material_type}，格式：{material.file_kind}）"]
    for seg in material.segments:
        text = seg.text
        if len(text) > max_chars_per_segment:
            text = text[:max_chars_per_segment] + "……[已截断]"
        lines.append(f"[{seg.location}] {text}")
    return "\n".join(lines)


def build_messages(
    process: str,
    rules: list[Rule],
    materials: list[ExtractedMaterial],
) -> list[dict[str, str]]:
    """构造 chat.completions 的 messages。"""
    process_label = PROCESS_LABEL.get(process, process)
    rule_list = [_rule_to_prompt_obj(r) for r in rules]
    materials_text = "\n\n".join(_material_to_text(m) for m in materials)

    user_content = f"""## 登记流程
{process_label}

## 本次需要审查的规则（共 {len(rules)} 条，请逐条独立判断）
```json
{json.dumps(rule_list, ensure_ascii=False, indent=2)}
```

## 申请材料

{materials_text}

## 输出要求
{OUTPUT_SCHEMA_HINT}
"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
