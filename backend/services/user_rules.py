"""用户新增规则存储（JSON 文件）。"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .schemas import ProcessType, RiskLevel

USER_RULES_FILE = Path(__file__).resolve().parent.parent / "data" / "user_rules.json"
USER_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)


class UserRule(BaseModel):
    rule_id: str
    process: ProcessType  # pre_report | initial
    applicable_materials: list[str] = Field(default_factory=list)
    rule_text: str
    risk_level: RiskLevel = "中风险"
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
) -> UserRule:
    rules = _load_all()
    new_rule = UserRule(
        rule_id=f"USER-{uuid.uuid4().hex[:8].upper()}",
        process=process,
        applicable_materials=applicable_materials,
        rule_text=rule_text.strip(),
        risk_level=risk_level,
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


def to_review_rule(ur: UserRule):
    """把 UserRule 转成 review_service 使用的 Rule。"""
    from .schemas import Rule

    return Rule(
        rule_id=ur.rule_id,
        registration_type="事前报告" if ur.process == "pre_report" else "初始登记",
        rule_name="用户新增规则",
        rule_text=ur.rule_text,
        basis_file="用户新增规则",
        basis_text=ur.rule_text,
        review_dimension="用户新增规则",
        applicable_materials=ur.applicable_materials,
        review_method="ai",
        check_type="语义条件判断",
        risk_level=ur.risk_level,
        ai_check_focus=["按规则文本判断材料是否存在违规或不规范"],
        evidence_requirement="请指出涉及的材料、表名、字段、页码或文本片段。",
        enabled=ur.enabled,
        demo_enabled=ur.enabled,
    )
