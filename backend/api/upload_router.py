"""上传 / 删除 / 列表 接口。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..services.material_parser import guess_material_type
from ..services.upload_store import (
    delete_upload,
    find_duplicate,
    list_uploads,
    load_meta,
    save_upload,
)

router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    material_type: Optional[str] = Form(default=None),
    process: Optional[str] = Form(default=None),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")

    name = file.filename or "unnamed"
    # 同 process + 同文件名 + 同材料类型 → 视为重复
    # 注意：material_type 若未传入，按 save_upload 同样的策略 guess 一次，避免漏判
    effective_type = material_type or guess_material_type(name)
    dup = find_duplicate(
        original_name=name,
        material_type=effective_type,
        process=process,
    )
    if dup is not None:
        raise HTTPException(
            status_code=409,
            detail=f"该文件（{name}）已存在于当前流程，不允许重复添加",
        )

    meta = save_upload(
        original_name=name,
        content=content,
        material_type=material_type,
        process=process,
    )
    return meta


@router.get("")
def list_all_uploads(process: Optional[str] = None):
    items = list_uploads()
    if process:
        items = [m for m in items if m.get("process") == process]
    return items


@router.get("/{file_id}")
def get_upload_meta(file_id: str):
    meta = load_meta(file_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"文件 {file_id} 不存在")
    return meta


@router.delete("/{file_id}")
def remove_upload(file_id: str):
    ok = delete_upload(file_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"文件 {file_id} 不存在")
    return {"deleted": file_id}
