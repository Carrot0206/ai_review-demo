from __future__ import annotations

import re

from ..models.schemas import ExtractedMaterial, MaterialSegment
from .rule_library import LibraryRule


MAX_JSON_SEGMENTS = 80
MAX_TEXT_SEGMENTS = 24


def _material_matches(material: ExtractedMaterial, label: str) -> bool:
    label = str(label or "").strip()
    haystack = f"{material.material_name} {material.material_type}"
    if not label or label in haystack or material.material_type in label:
        return True
    if "模板" in label and material.material_type == "申报模板":
        return True
    if "申请书" in label and material.material_type == "申请书":
        return True
    if ("信托文件" in label or "信托合同" in label) and material.material_type == "信托文件样本":
        return True
    if ("清算报告" in label or "附件" in label) and material.material_type == "其他附件":
        return True
    return False


def _keywords(rules: list[LibraryRule]) -> list[str]:
    items: list[str] = []
    for rule in rules:
        items.extend([rule.rule_name, rule.table_name, rule.field_path, rule.trigger_condition])
        items.extend(re.findall(r"【([^】]{2,30})】|“([^”]{2,30})”", rule.rule_text))
    flattened: list[str] = []
    for item in items:
        if isinstance(item, tuple):
            flattened.extend(part for part in item if part)
        elif item:
            flattened.append(str(item))
    output: list[str] = []
    for item in flattened:
        for token in re.split(r"[.。；;，,、\s]+", item):
            token = token.strip()
            if len(token) >= 2 and token not in output:
                output.append(token)
    return output


def _slice_segments(material: ExtractedMaterial, keywords: list[str]) -> tuple[list[MaterialSegment], bool]:
    matches = [
        index
        for index, segment in enumerate(material.segments)
        if any(keyword in f"{segment.location} {segment.text}" for keyword in keywords)
    ]
    if not matches:
        return material.segments, True
    selected_indexes: set[int] = set()
    for index in matches:
        selected_indexes.add(index)
        if index > 0:
            selected_indexes.add(index - 1)
        if index + 1 < len(material.segments):
            selected_indexes.add(index + 1)
    limit = MAX_JSON_SEGMENTS if material.file_kind == "json" or material.material_type == "申报模板" else MAX_TEXT_SEGMENTS
    selected = [material.segments[index] for index in sorted(selected_indexes)[:limit]]
    if len(selected) < 2 and len(material.segments) > len(selected):
        return material.segments, True
    return selected, False


def select_material_context(
    rules: list[LibraryRule],
    materials: list[ExtractedMaterial],
) -> tuple[list[ExtractedMaterial], list[str], bool]:
    labels = [label for rule in rules for label in rule.applicable_materials]
    selected_materials = [
        material
        for material in materials
        if not labels or any(_material_matches(material, label) for label in labels)
    ]
    if not selected_materials:
        selected_materials = list(materials)
    keywords = _keywords(rules)
    output: list[ExtractedMaterial] = []
    fallback = False
    for material in selected_materials:
        segments, used_full = _slice_segments(material, keywords)
        fallback = fallback or used_full
        output.append(material.model_copy(update={"segments": segments}))
    return output, [material.material_name for material in output], fallback

