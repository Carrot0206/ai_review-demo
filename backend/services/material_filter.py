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
    "申报模板": "申报模板",
    # 申请书
    "初始登记申请书": "申请书",
    "事前报告申请书": "申请书",
    "申请书": "申请书",
    # 信托文件样本
    "信托文件样本": "信托文件样本",
    "信托文件": "信托文件样本",
    "信托合同": "信托文件样本",
    # 其他附件
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
        return "申报模板"
    if "申请书" in t:
        return "申请书"
    if "信托文件" in t or "信托合同" in t:
        return "信托文件样本"
    return None


def _is_cross_material_rule(r: Rule) -> bool:
    """判断一条规则是否属于"跨材料一致性"类，需要全发材料。

    严格触发条件（任一即可）：
    - check_type == "跨材料一致性"
    - rule_name 含「一致性」

    特别地：以前曾把 "监管合规红线" review_dimension、"含 一致" check_type
    也算跨材料，这样会让大量"模板专属"规则（监管口径符合性/条件性必填等）
    被整批降级全发，把申请书塞进对它们无意义的输入。按用户原则——模板字段
    类规则的数据来源仅为申报模板 JSON——这里收紧到严格匹配。
    """
    ct = (r.check_type or "")
    rn = (r.rule_name or "")
    if ct == "跨材料一致性":
        return True
    if "一致性" in rn:
        return True
    return False


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
    if any(_is_cross_material_rule(r) for r in rules_list):
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
