"""按规则的 applicable_materials 标签裁剪材料。

规则里写的 applicable_materials 用的是"业务名"（例如 "初始登记申报模板JSON"），
材料解析时写入的 material_type 用的是"通用类型名"（例如 "申报模板"），
两套词表对不齐，需要在这里做一次映射归一化。

若 group 内任意一条规则的 applicable_materials 为空，
本批次回退为"全发"——以避免漏检（旧行为）。
"""
from __future__ import annotations

from typing import Iterable, Optional

from .schemas import ExtractedMaterial, Rule


# 规则的 applicable_materials 标签 → 材料 material_type 的对照表
RULE_TAG_TO_MATERIAL_TYPE: dict[str, str] = {
    # 申报模板
    "初始登记申报模板JSON": "申报模板",
    "事前报告模板JSON": "申报模板",
    "终止登记申报模板JSON": "申报模板",
    "预登记产品EXCEL模板.json": "申报模板",
    "申报模板": "申报模板",
    # 重新申请预登记 baseline / 专项附件
    "原预登记申报模板JSON": "原预登记申报模板JSON",
    "原预登记系统记录": "原预登记系统记录",
    "baseline": "原预登记申报模板JSON",
    "Baseline": "原预登记申报模板JSON",
    "政信类证明材料": "政信类证明材料",
    "新型资产服务信托情况说明": "新型资产服务信托情况说明",
    "信托预登记要素报告表": "其他附件",
    # 申请书
    "初始登记申请书": "申请书",
    "事前报告申请书": "申请书",
    "终止登记申请书": "申请书",
    "申请书": "申请书",
    # 信托文件样本
    "信托文件样本": "信托文件样本",
    "信托文件": "信托文件样本",
    "信托合同": "信托文件样本",
    # 其他附件
    "清算报告": "其他附件",
    "受托人出具的清算报告": "其他附件",
    "其他附件": "其他附件",
    "法律、行政法规、国家金融监督管理总局要求的其他文件": "其他附件",
}


def _normalize_rule_tag(tag: str) -> Optional[str]:
    """单个 applicable_materials 标签 → material_type。

    未命中映射表时返回 None（视作未知，调用方按降级处理）。
    """
    t = (tag or "").strip()
    if not t:
        return None
    if t in RULE_TAG_TO_MATERIAL_TYPE:
        return RULE_TAG_TO_MATERIAL_TYPE[t]
    # 兜底：包含关键字
    if "模板" in t:
        if "原预登记" in t:
            return "原预登记申报模板JSON"
        return "申报模板"
    if "申请书" in t:
        return "申请书"
    if "信托文件" in t or "信托合同" in t:
        return "信托文件样本"
    if "清算报告" in t:
        return "其他附件"
    if "原预登记" in t or "baseline" in t.lower():
        return "原预登记申报模板JSON"
    if "系统记录" in t:
        return "原预登记系统记录"
    if "政信" in t or "融资平台债务" in t:
        return "政信类证明材料"
    if "情况说明" in t or "新型资产服务信托" in t:
        return "新型资产服务信托情况说明"
    return None


def is_explicit_cross_document_rule(r: Rule) -> bool:
    """判断一条规则是否真的需要跨文件核对。

    初始登记要素审查中，"跨材料数据逻辑校验库"和"跨材料一致性"经常表示
    申报模板 JSON 内部跨表/跨字段逻辑，不等于申请书与模板核对。只有规则的
    适用材料和规则文本同时明确指向申请书/信托文件，才按跨文件处理。
    """
    tags = " ".join(r.applicable_materials or [])
    has_template = "模板" in tags or "JSON" in tags
    has_external_doc = (
        "申请书" in tags
        or "信托文件" in tags
        or "信托合同" in tags
        or "清算报告" in tags
        or "其他附件" in tags
    )
    if not (has_template and has_external_doc):
        return False

    text = " ".join(
        str(x or "")
        for x in [
            r.rule_name,
            r.rule_text,
            r.check_type,
            r.trigger_condition,
            getattr(r, "machine_params", ""),
            " ".join(r.ai_check_focus or []),
        ]
    )
    mentions_external_doc = (
        "申请书" in text
        or "信托文件" in text
        or "信托合同" in text
        or "清算报告" in text
        or "佐证" in text
    )
    mentions_compare = "一致" in text or "==" in text or "相同" in text or "对应" in text
    return mentions_external_doc and mentions_compare


def materials_needed_by_group(rules: Iterable[Rule]) -> Optional[set[str]]:
    """计算本批规则需要的 material_type 集合。

    返回：
      - set[str]：本批规则的 applicable_materials 归一并集
      - None：表示"全发降级"——本批至少有一条规则属于跨材料一致性类，
        或缺标签 / 含无法归一化的标签。

    注意：不再无条件追加"申请书"。模板字段类检查不应让 LLM 在申请书里查找。
    """
    rules_list = list(rules)
    # 一致性 / 跨材料类规则 → 强制全发（让申请书与模板都在）
    if any(is_explicit_cross_document_rule(r) for r in rules_list):
        return None

    needed: set[str] = set()
    for r in rules_list:
        tags = r.applicable_materials or []
        if not tags:
            # 任意一条规则缺标签 → 降级
            return None
        for tag in tags:
            mt = _normalize_rule_tag(tag)
            if mt is None:
                # 出现无法归一化的未知标签也降级，避免漏检
                return None
            needed.add(mt)
    return needed


def filter_materials(
    materials: list[ExtractedMaterial],
    needed: Optional[set[str]],
) -> list[ExtractedMaterial]:
    """按 needed 集合过滤材料；needed=None 时不过滤（全发）。"""
    if needed is None:
        return list(materials)
    return [m for m in materials if m.material_type in needed]
