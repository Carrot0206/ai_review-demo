"""Prompt 组装：把规则数组 + 材料片段拼成 DeepSeek 的对话消息。

设计原则：
- system 强约束：只对给定规则判断、未发现问题不输出、必须返回合法 JSON。
- user 给出规则数组（精简字段）+ 材料文本片段（含 location 坐标）。
- 不让模型生成 rule_basis / risk_level —— 后端根据 rule_id 回填。
"""
from __future__ import annotations

import json
from typing import Any, Optional

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
9. 【缺失字段类问题特别约定】：
   - location 必须精确到字段级，写成"表名.字段名"，例如 "产品特征.是否城市更新"、"产品基本信息.信托产品全称"；禁止只写表名（如 "产品特征"、"产品特征表"）这种粗粒度路径。
   - 每个缺失字段必须独立成为一条 issue，不允许把多个不同字段的缺失合并到同一条。
   - value 写成 "缺失:<字段名>" 的形式（例如 "缺失:是否城市更新"），不允许只写泛指的 "缺失"、"未填写"、"字段缺失"。
10. 【允许性 vs 禁止性 严格区分】：
   - 仅当规则原文为"应当 / 必须 / 不得 / 禁止 / 必填 / 严禁"等强约束、或明确的"==/!=/必须等于"等条件式校验时，才能据此输出 issue。
   - 规则原文为"可 / 可以 / 可通过此栏位 / 也可 / 非必填 / 选填 / 填报说明 / 示例"等允许性、说明性、举例性表述时，仅作为对该栏位用途的说明使用，禁止据此判定违规；即便实际填报内容与"示例用途"不同，也不要输出 issue。
   - 不确定一条规则属于强约束还是允许性时，按允许性处理，不输出 issue。
11. 【跨材料字段级一致性 · 仅在规则显式声明时触发】：
   - 仅当规则的 rule_name 含"一致性"或 check_type 为"跨材料一致性"，且 applicable_materials 同时包含申请书与申报模板时，才进行跨材料核对。
   - 跨材料核对要求：两份材料中都能定位到同名字段或同义字段时，才比对取值；issue_location 同时给出两份材料中的真实取值。
   - 若规则不属于一致性类（如"条件性必填"、"监管口径符合性"、"语义条件判断"等），即便申请书在本批输入里，也不得到申请书中查找该字段。
12. 【模板字段的数据来源边界】：
   - 《初始登记要素表及填表说明》/《事前报告要素表及填表说明》中定义的所有字段，其所有类型检查（必填 / 格式 / 枚举值 / 取值范围 / 字段间逻辑 / 数值校验等）的数据来源仅为【申报模板 JSON】。
   - 申请书不是这些字段的填报数据源；申请书未提及某模板字段不视为"字段缺失"，更不得据此输出 issue。
   - 典型模板专属字段示例："是否信托受益权转让"、"开放频度"、"是否为结构化信托"、"约定优先劣后受益权比例"、"是否金融通道业务"、"受托职责"、"受益人是否可查询"、"资产管理信托分类"、"受益凭据编号"等。对这些字段的检查必须在 material_type=申报模板 的材料中进行，禁止在申请书正文中查找。
   - 唯一例外：rule_name 含"一致性"或 check_type=跨材料一致性 的规则，按第 11 条进行跨材料比对。
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
location 示例（必须给到字段级，禁止只写表名）：
  - "产品基本信息.信托产品全称"
  - "产品特征.是否城市更新"
  - "受益人信息.受益人类型"
缺失字段示例（一字段一 issue，value 带字段名）：
  {"material_name": "初始登记模板_xxx.json", "location": "产品特征.是否城市更新", "value": "缺失:是否城市更新"}
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
    material_filter: Optional[set[str]] = None,
) -> list[dict[str, str]]:
    """构造 chat.completions 的 messages。

    material_filter：限定本次只送入哪些 material_type 的材料；为 None 表示全发。
    若过滤后为空，仍保留 1 行占位提示，使模型可以走"未发现问题"分支。
    """
    process_label = PROCESS_LABEL.get(process, process)
    rule_list = [_rule_to_prompt_obj(r) for r in rules]

    if material_filter is None:
        filtered = list(materials)
    else:
        filtered = [m for m in materials if m.material_type in material_filter]

    if filtered:
        materials_text = "\n\n".join(_material_to_text(m) for m in filtered)
    else:
        materials_text = "### 无可审材料（本批次依赖的材料类型在本次上传中未提供）"

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
