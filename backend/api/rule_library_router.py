"""Management-only rule library API."""
from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services.rule_library import (
    LibraryProcess,
    LibraryRuleInput,
    build_import_template,
    build_visual_rule,
    copy_rule,
    create_rule,
    create_rules_bulk,
    delete_rule,
    delete_rules,
    delete_rules_by_process,
    get_rule,
    list_rules,
    parse_rule_workbook,
    set_rule_enabled,
    update_rule,
)


router = APIRouter(prefix="/api/rule-library", tags=["rule-library"])


class EnabledUpdate(BaseModel):
    enabled: bool


class BatchDelete(BaseModel):
    rule_ids: list[str]


def _view(rule):
    return {**rule.model_dump(), "visual_rule": build_visual_rule(rule)}


@router.get("/rules")
def get_rules(process: LibraryProcess = Query(...)):
    rules = list_rules(process)
    return {
        "process": process,
        "total": len(rules),
        "script_count": sum(rule.review_method == "script" for rule in rules),
        "ai_count": sum(rule.review_method == "ai" for rule in rules),
        "enabled_count": sum(rule.enabled for rule in rules),
        "rules": [_view(rule) for rule in rules],
    }


@router.get("/rules/{rule_id}")
def get_rule_detail(rule_id: str):
    rule = get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")
    return _view(rule)


@router.post("/rules")
def add_rule(payload: LibraryRuleInput):
    try:
        return _view(create_rule(payload))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/rules/{rule_id}")
def edit_rule(rule_id: str, payload: LibraryRuleInput):
    try:
        rule = update_rule(rule_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if rule is None:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")
    return _view(rule)


@router.post("/rules/{rule_id}/copy")
def duplicate_rule(rule_id: str):
    rule = copy_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")
    return _view(rule)


@router.patch("/rules/{rule_id}/enabled")
def change_rule_enabled(rule_id: str, payload: EnabledUpdate):
    rule = set_rule_enabled(rule_id, payload.enabled)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")
    return _view(rule)


@router.post("/rules/batch-delete")
def remove_rules(payload: BatchDelete):
    if not payload.rule_ids:
        raise HTTPException(status_code=400, detail="rule_ids 不能为空")
    deleted = delete_rules(payload.rule_ids)
    return {"deleted_count": deleted, "requested_count": len(payload.rule_ids)}


@router.delete("/rules/by-process")
def remove_rules_by_process(process: LibraryProcess = Query(...)):
    deleted = delete_rules_by_process(process)
    return {"process": process, "deleted_count": deleted}


@router.delete("/rules/{rule_id}")
def remove_rule(rule_id: str):
    if not delete_rule(rule_id):
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")
    return {"deleted": True, "rule_id": rule_id}


async def _read_excel(file: UploadFile) -> tuple[str, bytes]:
    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xlsm 规则表")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="规则表不能为空")
    return filename, content


@router.post("/import/preview")
async def preview_import(process: LibraryProcess, file: UploadFile = File(...)):
    filename, content = await _read_excel(file)
    report = parse_rule_workbook(
        content,
        filename=filename,
        process=process,
        existing_ids={rule.rule_id for rule in list_rules()},
    )
    return {
        **report.model_dump(exclude={"rules"}),
        "preview": [_view(rule) for rule in report.rules[:20]],
    }


@router.post("/import/commit")
async def commit_import(process: LibraryProcess, file: UploadFile = File(...)):
    filename, content = await _read_excel(file)
    report = parse_rule_workbook(
        content,
        filename=filename,
        process=process,
        existing_ids={rule.rule_id for rule in list_rules()},
    )
    if not report.valid:
        raise HTTPException(
            status_code=400,
            detail={
                **report.model_dump(exclude={"rules"}),
                "message": "规则表校验失败，未导入任何规则",
            },
        )
    try:
        saved = create_rules_bulk(report.rules)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "filename": filename,
        "process": process,
        "imported_count": len(saved),
        "script_count": report.script_count,
        "ai_count": report.ai_count,
    }


@router.get("/template")
def download_template(process: LibraryProcess = Query(...)):
    content = build_import_template(process)
    filename = f"{process}_rule_library_template.xlsx"
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
