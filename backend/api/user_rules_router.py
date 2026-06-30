"""用户新增规则 CRUD。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.schemas import ProcessType, RiskLevel
from ..services.user_rules import (
    add_user_rule,
    delete_user_rule,
    list_user_rules,
    update_user_rule,
)

router = APIRouter(prefix="/api/user-rules", tags=["user-rules"])


class UserRuleCreate(BaseModel):
    process: ProcessType
    applicable_materials: list = []
    rule_text: str
    risk_level: RiskLevel = "中风险"
    review_dimension: str = "用户新增规则"
    check_type: str = "语义条件判断"
    table_name: str = ""
    field_name: str = ""
    trigger_condition: str = ""


class UserRuleUpdate(BaseModel):
    applicable_materials: Optional[list] = None
    rule_text: Optional[str] = None
    risk_level: Optional[RiskLevel] = None
    review_dimension: Optional[str] = None
    check_type: Optional[str] = None
    table_name: Optional[str] = None
    field_name: Optional[str] = None
    trigger_condition: Optional[str] = None


@router.get("")
def get_user_rules(process: Optional[ProcessType] = None):
    return [r.model_dump() for r in list_user_rules(process)]


@router.post("")
def create_user_rule(payload: UserRuleCreate):
    if not payload.rule_text.strip():
        raise HTTPException(status_code=400, detail="规则内容不能为空")
    rule = add_user_rule(
        process=payload.process,
        applicable_materials=payload.applicable_materials,
        rule_text=payload.rule_text,
        risk_level=payload.risk_level,
        review_dimension=payload.review_dimension,
        check_type=payload.check_type,
        table_name=payload.table_name,
        field_name=payload.field_name,
        trigger_condition=payload.trigger_condition,
    )
    return rule.model_dump()


@router.put("/{rule_id}")
def edit_user_rule(rule_id: str, payload: UserRuleUpdate):
    if payload.rule_text is not None and not payload.rule_text.strip():
        raise HTTPException(status_code=400, detail="规则内容不能为空")
    rule = update_user_rule(
        rule_id,
        applicable_materials=payload.applicable_materials,
        rule_text=payload.rule_text,
        risk_level=payload.risk_level,
        review_dimension=payload.review_dimension,
        check_type=payload.check_type,
        table_name=payload.table_name,
        field_name=payload.field_name,
        trigger_condition=payload.trigger_condition,
    )
    if rule is None:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")
    return rule.model_dump()


@router.delete("/{rule_id}")
def remove_user_rule(rule_id: str):
    ok = delete_user_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")
    return {"deleted": rule_id}
