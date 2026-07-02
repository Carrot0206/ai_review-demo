"""用户新增规则存储（JSON 文件）。"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .schemas import PROCESS_LABEL, ProcessType, RiskLevel

USER_RULES_FILE = Path(__file__).resolve().parent.parent / "data" / "user_rules.json"
USER_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)


class UserRule(BaseModel):
    rule_id: str
    process: ProcessType
    applicable_materials: list[str] = Field(default_factory=list)
    rule_text: str
    risk_level: RiskLevel = "中风险"
    review_dimension: str = "用户新增规则"
    check_type: str = "语义条件判断"
    table_name: str = ""
    field_name: str = ""
    trigger_condition: str = ""
    created_at: int = 0
    enabled: bool = True


def _load_all() -> list[UserRule]:
    if not USER_RULES_FILE.exists():
        return []
    raw = json.loads(USER_RULES_FILE.read_text(encoding="utf-8"))
    return [UserRule.model_validate(r) for r in raw.get("rules", [])]


def _save_all(rules: list[UserRule]) -> None:
    USER_RULES_FILE.write_text(
        json.dumps(
            {"rules": [r.model_dump() for r in rules]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def list_user_rules(process: Optional[ProcessType] = None) -> list[UserRule]:
    rules = _load_all()
    if process:
        rules = [r for r in rules if r.process == process]
    return rules


def add_user_rule(
    *,
    process: ProcessType,
    applicable_materials: list[str],
    rule_text: str,
    risk_level: RiskLevel = "中风险",
    review_dimension: str = "用户新增规则",
    check_type: str = "语义条件判断",
    table_name: str = "",
    field_name: str = "",
    trigger_condition: str = "",
) -> UserRule:
    rules = _load_all()
    new_rule = UserRule(
        rule_id=f"USER-{uuid.uuid4().hex[:8].upper()}",
        process=process,
        applicable_materials=applicable_materials,
        rule_text=rule_text.strip(),
        risk_level=risk_level,
        review_dimension=(review_dimension or "用户新增规则").strip(),
        check_type=(check_type or "语义条件判断").strip(),
        table_name=(table_name or "").strip(),
        field_name=(field_name or "").strip(),
        trigger_condition=(trigger_condition or "").strip(),
        created_at=int(time.time()),
        enabled=True,
    )
    rules.append(new_rule)
    _save_all(rules)
    return new_rule


def delete_user_rule(rule_id: str) -> bool:
    rules = _load_all()
    new = [r for r in rules if r.rule_id != rule_id]
    if len(new) == len(rules):
        return False
    _save_all(new)
    return True


def update_user_rule(
    rule_id: str,
    *,
    applicable_materials: Optional[list[str]] = None,
    rule_text: Optional[str] = None,
    risk_level: Optional[RiskLevel] = None,
    review_dimension: Optional[str] = None,
    check_type: Optional[str] = None,
    table_name: Optional[str] = None,
    field_name: Optional[str] = None,
    trigger_condition: Optional[str] = None,
) -> Optional[UserRule]:
    """按 rule_id 局部更新用户规则。返回更新后的规则；找不到则返回 None。"""
    rules = _load_all()
    for i, r in enumerate(rules):
        if r.rule_id != rule_id:
            continue
        if applicable_materials is not None:
            r.applicable_materials = applicable_materials
        if rule_text is not None:
            r.rule_text = rule_text.strip()
        if risk_level is not None:
            r.risk_level = risk_level
        if review_dimension is not None:
            r.review_dimension = (review_dimension or "用户新增规则").strip()
        if check_type is not None:
            r.check_type = (check_type or "语义条件判断").strip()
        if table_name is not None:
            r.table_name = (table_name or "").strip()
        if field_name is not None:
            r.field_name = (field_name or "").strip()
        if trigger_condition is not None:
            r.trigger_condition = (trigger_condition or "").strip()
        rules[i] = r
        _save_all(rules)
        return r
    return None


def to_review_rule(ur: UserRule):
    """把 UserRule 转成 review_service 使用的 Rule。"""
    from .schemas import Rule

    return Rule(
        rule_id=ur.rule_id,
        registration_type=PROCESS_LABEL.get(ur.process, ur.process),
        rule_name="用户新增规则",
        rule_text=ur.rule_text,
        basis_file="用户新增规则",
        basis_text=ur.rule_text,
        review_dimension=ur.review_dimension or "用户新增规则",
        table_name=ur.table_name or "",
        field_name=ur.field_name or "",
        applicable_materials=ur.applicable_materials,
        review_method="ai",
        check_type=ur.check_type or "语义条件判断",
        trigger_condition=ur.trigger_condition or "",
        risk_level=ur.risk_level,
        ai_check_focus=["按规则文本判断材料是否存在违规或不规范"],
        evidence_requirement="请指出涉及的材料、表名、字段、页码或文本片段。",
        enabled=ur.enabled,
        demo_enabled=ur.enabled,
    )
