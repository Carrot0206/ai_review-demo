"""上传规则版本 API。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from ..services.rule_sets import (
    activate_rule_set,
    create_rule_set,
    delete_rule_set,
    list_rule_sets,
    load_rule_set_rules,
)
from ..services.schemas import ProcessType

router = APIRouter(prefix="/api/rule-sets", tags=["rule-sets"])


@router.get("")
def get_rule_sets(process: Optional[ProcessType] = Query(None)):
    return {"rule_sets": [item.model_dump() for item in list_rule_sets(process)]}


@router.post("/import")
async def import_rule_set(process: ProcessType, file: UploadFile = File(...)):
    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xlsm 规则表")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="规则表不能为空")
    try:
        meta = create_rule_set(process=process, filename=filename, content=content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"规则表解析失败：{e}")
    return meta.model_dump()


@router.post("/{rule_set_id}/activate")
def activate(rule_set_id: str):
    meta = activate_rule_set(rule_set_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"规则版本 {rule_set_id} 不存在")
    return meta.model_dump()


@router.get("/{rule_set_id}/rules")
def get_rule_set_rules(rule_set_id: str):
    rules = load_rule_set_rules(rule_set_id)
    return {"rule_set_id": rule_set_id, "total": len(rules), "rules": [r.model_dump() for r in rules]}


@router.delete("/{rule_set_id}")
def delete(rule_set_id: str):
    meta = delete_rule_set(rule_set_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"规则版本 {rule_set_id} 不存在")
    return {
        "deleted": True,
        "rule_set_id": rule_set_id,
        "filename": meta.filename,
        "process": meta.process,
        "was_active": meta.active,
    }
