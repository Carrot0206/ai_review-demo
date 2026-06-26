"""GET /api/rules — 加载某流程的内置规则。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..services.rule_loader import load_rules, split_for_ai_and_human
from ..services.schemas import ProcessType
from ..services.user_rules import list_user_rules

router = APIRouter(prefix="/api/rules", tags=["rules"])


@router.get("")
def get_rules(process: ProcessType = Query(...)):
    try:
        rules = load_rules(process)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    ai_rules, human_rules = split_for_ai_and_human(rules)

    # 仅返回前端展示需要的字段
    def to_card(r):
        return {
            "rule_id": r.rule_id,
            "rule_name": r.rule_name,
            "rule_text": r.rule_text,
            "review_dimension": r.review_dimension,
            "check_type": r.check_type,
            "risk_level": r.risk_level,
            "applicable_materials": r.applicable_materials,
            "basis_file": r.basis_file,
            "needs_human": r.needs_human,
        }

    return {
        "process": process,
        "total": len(rules),
        "ai_count": len(ai_rules),
        "human_count": len(human_rules),
        "rules": [to_card(r) for r in rules],
        "user_rules": [r.model_dump() for r in list_user_rules(process)],
    }
