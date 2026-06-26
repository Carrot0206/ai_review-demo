"""上传 / 删除 / 列表 接口。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..services.upload_store import (
    delete_upload,
    list_uploads,
    load_meta,
    save_upload,
)

router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    material_type: Optional[str] = Form(default=None),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    meta = save_upload(
        original_name=file.filename or "unnamed",
        content=content,
        material_type=material_type,
    )
    return meta


@router.get("")
def list_all_uploads():
    return list_uploads()


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
