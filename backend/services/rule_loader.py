"""规则加载、过滤与分组。

- 按流程加载 data/rules/ 下的规则 JSON
- 过滤 enabled=false / demo_enabled=false
- 识别"版式/显著位置"类规则 → needs_human=True，从 AI 批次剥离
- 按 review_dimension 分组（复合维度按主维度归一），每组 ≤ MAX_GROUP_SIZE
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .material_filter import is_explicit_cross_document_rule
from .schemas import ProcessType, Rule

RULES_DIR = Path(__file__).resolve().parent.parent / "data" / "rules"

RULE_FILE_MAP = {
    "pre_report": "rules_pre_report.json",
    "initial": "rules_initial_registration_structured.json",
    "pre_registration": "rules_pre_registration.json",
    "termination": "rules_termination.json",
}

# 触发"需人工复核"的关键字（命中即剥离出 AI 批次）
HUMAN_REVIEW_CHECK_TYPES = {"版式位置", "版式", "显著位置"}

# 单组规则上限（避免 prompt 过长 / 模型注意力分散）
MAX_GROUP_SIZE = 4


def _normalize_dimension(raw: str) -> str:
    """复合维度按第一个分号前内容归一，去掉换行。"""
    if not raw:
        return "其他"
    head = raw.replace("\n", "").split("；")[0].split(";")[0].strip()
    return head or "其他"


def _is_human_review(rule: Rule) -> bool:
    check_type = (rule.check_type or "").strip()
    if check_type in HUMAN_REVIEW_CHECK_TYPES:
        return True
    # 命中任意关键字
    for kw in HUMAN_REVIEW_CHECK_TYPES:
        if kw and kw in check_type:
            return True
    return False


def load_rules(process: ProcessType) -> list[Rule]:
    """加载某流程的全部规则（已过滤 enabled / demo_enabled）。"""
    filename = RULE_FILE_MAP[process]
    path = RULES_DIR / filename
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    rules: list[Rule] = []
    for raw in data["rules"]:
        rule = Rule.model_validate(raw)
        if not rule.enabled or not rule.demo_enabled:
            continue
        rule.needs_human = _is_human_review(rule)
        rules.append(rule)
    return rules


def split_for_ai_and_human(rules: Iterable[Rule]) -> tuple[list[Rule], list[Rule]]:
    """拆分为 AI 批次规则 与 需人工复核规则。"""
    ai_rules: list[Rule] = []
    human_rules: list[Rule] = []
    for r in rules:
        (human_rules if r.needs_human else ai_rules).append(r)
    return ai_rules, human_rules


def group_by_dimension(rules: list[Rule], max_group_size: int = MAX_GROUP_SIZE) -> list[list[Rule]]:
    """按 review_dimension 分组，再按 max_group_size 切片。

    真实跨文件规则单独成桶，避免申请书/信托文件上下文污染同维度下的模板内规则。
    """
    bucket: dict[tuple[str, str, str], list[Rule]] = {}
    for r in rules:
        dim = _normalize_dimension(r.review_dimension)
        scope = "cross_document" if is_explicit_cross_document_rule(r) else "template_or_internal"
        source_sheet = getattr(r, "source_sheet", "") or ""
        key = (dim, scope, source_sheet)
        bucket.setdefault(key, []).append(r)

    groups: list[list[Rule]] = []
    for _, items in bucket.items():
        for i in range(0, len(items), max_group_size):
            groups.append(items[i : i + max_group_size])
    return groups


def describe_group(group: list[Rule]) -> str:
    """给一组规则起一个用于日志/批次标识的描述。"""
    if not group:
        return "empty"
    dim = _normalize_dimension(group[0].review_dimension)
    return f"{dim}({len(group)}条)"
