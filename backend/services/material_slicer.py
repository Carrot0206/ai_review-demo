"""材料片段裁剪。

目标：在每条规则仍由 AI 审核的前提下，减少 prompt 中无关材料片段。

策略：
- 申报模板 JSON：优先按 table_name / field_name / trigger_condition 做字段级裁剪。
- 申请书 / 信托文件 / 其他附件：按规则关键词做弱检索，命中不足则回退全文。
- 任意材料裁剪后为空或置信度不足时回退，避免因裁剪过度影响准确率。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import ExtractedMaterial, MaterialSegment, Rule


MIN_TOTAL_SEGMENTS = 4
MAX_TEXT_SEGMENTS = 18
MAX_JSON_TABLE_SEGMENTS = 80

GENERIC_STOPWORDS = {
    "检查",
    "审核",
    "规则",
    "材料",
    "申请",
    "登记",
    "信托",
    "产品",
    "是否",
    "应",
    "应当",
    "必须",
    "不得",
    "禁止",
    "需要",
    "提供",
    "填写",
    "一致",
    "一致性",
    "完整",
    "准确",
    "真实",
    "合理",
    "合规",
}

BUSINESS_TERMS = [
    "信托产品全称",
    "信托产品名称",
    "产品全称",
    "产品名称",
    "受托职责",
    "受益人",
    "委托人",
    "信托期限",
    "信托规模",
    "收益分配",
    "结构化信托",
    "优先劣后",
    "受益权比例",
    "关联交易",
    "关联交易事项",
    "迟报原因",
    "迟报情况",
    "成立日期",
    "申报日期",
    "填表人",
    "签字",
    "盖章",
    "公章",
    "董事会批准",
    "金融通道业务",
    "资产管理信托",
]


@dataclass
class SliceResult:
    materials: list[ExtractedMaterial]
    enabled: bool
    original_segment_count: int = 0
    sliced_segment_count: int = 0
    fallback: bool = False
    confidence: str = "off"
    summary: str = "材料裁剪未开启"


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = (item or "").strip()
        if not clean:
            continue
        key = _norm(clean)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _trigger_tokens(trigger: str) -> list[str]:
    """从简单触发条件中抽取字段和值，例如 A=是 / 若A为是。"""
    if not trigger:
        return []
    raw = trigger.strip()
    parts = re.split(r"[=＝:：,，;；、\s]+|若|如果|当|则|为|是|时|且|并且", raw)
    return [p.strip("“”\"'（）()[]【】") for p in parts if len(p.strip()) >= 2]


def _quoted_terms(text: str) -> list[str]:
    terms: list[str] = []
    patterns = [
        r"“([^”]{2,30})”",
        r'"([^"]{2,30})"',
        r"'([^']{2,30})'",
        r"《([^》]{2,30})》",
    ]
    for pat in patterns:
        terms.extend(re.findall(pat, text or ""))
    return terms


def _rule_keywords(rule: Rule) -> list[str]:
    raw_terms: list[str] = []
    raw_terms.extend([rule.table_name, rule.field_name])
    raw_terms.extend(_trigger_tokens(rule.trigger_condition))
    raw_terms.extend(_quoted_terms(rule.rule_text))
    raw_terms.extend(_quoted_terms(rule.trigger_condition))

    source = " ".join(
        [
            rule.rule_name or "",
            rule.rule_text or "",
            rule.table_name or "",
            rule.field_name or "",
            rule.trigger_condition or "",
            " ".join(rule.ai_check_focus or []),
        ]
    )
    for term in BUSINESS_TERMS:
        if term in source:
            raw_terms.append(term)

    # 抽取较长中文词片段作为兜底关键词，避免完全依赖业务词表。
    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{3,20}", source):
        if token in GENERIC_STOPWORDS:
            continue
        if len(token) >= 3:
            raw_terms.append(token)

    return _dedupe(raw_terms)


def _group_keywords(rules: list[Rule]) -> list[str]:
    terms: list[str] = []
    for rule in rules:
        terms.extend(_rule_keywords(rule))
    return _dedupe(terms)


def _match_segment(seg: MaterialSegment, keywords: list[str]) -> int:
    hay = _norm(f"{seg.location} {seg.text}")
    score = 0
    for kw in keywords:
        nkw = _norm(kw)
        if not nkw:
            continue
        if nkw in hay:
            score += 3 if len(nkw) >= 5 else 1
    return score


def _select_with_neighbors(
    segments: list[MaterialSegment], matched_indexes: set[int], max_segments: int
) -> list[MaterialSegment]:
    wanted: set[int] = set()
    for idx in matched_indexes:
        wanted.add(idx)
        if idx > 0:
            wanted.add(idx - 1)
        if idx + 1 < len(segments):
            wanted.add(idx + 1)
    ordered = sorted(wanted)
    if len(ordered) > max_segments:
        # 优先保留原始命中，再补周边。
        priority = sorted(matched_indexes)
        rest = [i for i in ordered if i not in matched_indexes]
        ordered = (priority + rest)[:max_segments]
        ordered.sort()
    return [segments[i] for i in ordered]


def _slice_json_material(
    material: ExtractedMaterial, rules: list[Rule], keywords: list[str]
) -> tuple[list[MaterialSegment], bool, str]:
    segments = material.segments
    matched: set[int] = set()

    for idx, seg in enumerate(segments):
        loc = seg.location or ""
        text = seg.text or ""
        for rule in rules:
            table = (rule.table_name or "").strip()
            field = (rule.field_name or "").strip()
            trigger_terms = _trigger_tokens(rule.trigger_condition)
            if table and field and table in loc and field in loc:
                matched.add(idx)
            elif field and field in loc:
                matched.add(idx)
            elif table and table in loc:
                matched.add(idx)
            elif any(term and term in loc for term in trigger_terms):
                matched.add(idx)
        if idx not in matched and _match_segment(seg, keywords) > 0:
            matched.add(idx)
        # 保留空值字段的邻近定位信号，便于 AI 判断缺失。
        if text == "" and any(kw and kw in loc for kw in keywords):
            matched.add(idx)

    if not matched:
        return segments, True, "low"

    selected = [segments[i] for i in sorted(matched)]
    if len(selected) > MAX_JSON_TABLE_SEGMENTS:
        selected = selected[:MAX_JSON_TABLE_SEGMENTS]
    confidence = "high" if len(selected) >= 2 else "medium"
    return selected, False, confidence


def _slice_text_material(
    material: ExtractedMaterial, keywords: list[str]
) -> tuple[list[MaterialSegment], bool, str]:
    segments = material.segments
    if not keywords:
        return segments, True, "low"

    scored: list[tuple[int, int]] = []
    for idx, seg in enumerate(segments):
        score = _match_segment(seg, keywords)
        if score > 0:
            scored.append((score, idx))

    if not scored:
        return segments, True, "low"

    scored.sort(key=lambda x: (-x[0], x[1]))
    matched = {idx for _, idx in scored[: max(3, MAX_TEXT_SEGMENTS // 3)]}
    selected = _select_with_neighbors(segments, matched, MAX_TEXT_SEGMENTS)

    if len(selected) < 2 and len(segments) > len(selected):
        return segments, True, "low"
    confidence = "high" if len(scored) >= 3 else "medium"
    return selected, False, confidence


def slice_materials_for_group(
    rules: list[Rule],
    materials: list[ExtractedMaterial],
    *,
    enabled: bool,
) -> SliceResult:
    original_count = sum(len(m.segments) for m in materials)
    if not enabled:
        return SliceResult(
            materials=materials,
            enabled=False,
            original_segment_count=original_count,
            sliced_segment_count=original_count,
        )

    keywords = _group_keywords(rules)
    if not keywords:
        return SliceResult(
            materials=materials,
            enabled=True,
            original_segment_count=original_count,
            sliced_segment_count=original_count,
            fallback=True,
            confidence="low",
            summary="材料裁剪：未提取到有效关键词，已回退全文",
        )

    sliced_materials: list[ExtractedMaterial] = []
    fallback = False
    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    confidence = "high"
    parts: list[str] = []

    for material in materials:
        if material.file_kind == "json" or material.material_type == "申报模板":
            selected, did_fallback, conf = _slice_json_material(material, rules, keywords)
        else:
            selected, did_fallback, conf = _slice_text_material(material, keywords)

        if did_fallback:
            fallback = True
        if confidence_rank.get(conf, 1) < confidence_rank.get(confidence, 1):
            confidence = conf

        sliced_materials.append(
            ExtractedMaterial(
                material_name=material.material_name,
                material_type=material.material_type,
                file_kind=material.file_kind,
                segments=selected,
            )
        )
        parts.append(f"{material.material_name} {len(material.segments)}→{len(selected)}")

    sliced_count = sum(len(m.segments) for m in sliced_materials)
    if sliced_count < MIN_TOTAL_SEGMENTS and original_count > sliced_count:
        sliced_materials = materials
        sliced_count = original_count
        fallback = True
        confidence = "low"
        summary = "材料裁剪：命中片段过少，已回退全文"
    else:
        summary = "材料裁剪：" + "，".join(parts)
        if fallback:
            summary += "；部分材料命中不足已回退"

    return SliceResult(
        materials=sliced_materials,
        enabled=True,
        original_segment_count=original_count,
        sliced_segment_count=sliced_count,
        fallback=fallback,
        confidence=confidence,
        summary=summary,
    )
