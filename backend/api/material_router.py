"""规则引擎材料上传、解析与管理 API。"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from ..services.material_parser import SUPPORTED_EXTENSIONS
from ..services.material_store import (
    MAX_MATERIAL_UPLOAD_BYTES,
    DuplicateMaterialError,
    abort_material_upload,
    begin_material_upload,
    delete_material,
    finish_material_upload,
    list_materials,
    load_extracted_material,
    load_material_meta,
)
from ..services.rule_library import LibraryProcess


router = APIRouter(prefix="/api/rule-engine/materials", tags=["rule-engine-materials"])
CHUNK_SIZE = 1024 * 1024


@router.post("")
async def upload_material(
    file: UploadFile = File(...),
    process: LibraryProcess = Form(...),
    material_type: Optional[str] = Form(default=None),
):
    filename = Path(file.filename or "unnamed").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"暂不支持的材料类型：{suffix or '无扩展名'}")
    try:
        metadata, staging_path = begin_material_upload(filename, process, material_type)
    except DuplicateMaterialError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    total_size = 0
    try:
        with staging_path.open("wb") as output:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_MATERIAL_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="材料文件超过100MB限制")
                output.write(chunk)
        if total_size == 0:
            raise HTTPException(status_code=400, detail="文件为空")
        return await asyncio.to_thread(
            finish_material_upload,
            metadata["file_id"],
            staging_path,
            total_size,
        )
    except HTTPException:
        abort_material_upload(metadata["file_id"])
        raise
    except Exception as error:
        abort_material_upload(metadata["file_id"])
        raise HTTPException(status_code=500, detail=f"材料保存失败：{error}") from error
    finally:
        await file.close()


@router.get("")
def get_materials(process: Optional[LibraryProcess] = Query(default=None)):
    return list_materials(process)


@router.get("/{file_id}")
def get_material(file_id: str):
    try:
        metadata = load_material_meta(file_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"材料 {file_id} 不存在")
    return metadata


@router.get("/{file_id}/extracted")
def get_extracted_material(file_id: str):
    try:
        metadata = load_material_meta(file_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"材料 {file_id} 不存在")
    material = load_extracted_material(file_id)
    if material is None:
        reason = metadata.get("parse_error") or metadata.get("parse_status") or "未知原因"
        raise HTTPException(status_code=409, detail=f"材料尚未解析成功：{reason}")
    return material


@router.delete("/{file_id}")
def remove_material(file_id: str):
    try:
        deleted = delete_material(file_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not deleted:
        raise HTTPException(status_code=404, detail=f"材料 {file_id} 不存在")
    return {"deleted": file_id}
