"""规则引擎材料文件、元数据和解析结果的持久化服务。"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from ..models.schemas import ExtractedMaterial
from .material_parser import guess_material_type, parse_material


MATERIAL_UPLOAD_DIR = Path(
    os.getenv(
        "MATERIAL_UPLOAD_DIR",
        Path(__file__).resolve().parent.parent / "data" / "materials",
    )
)
MAX_MATERIAL_UPLOAD_BYTES = int(os.getenv("MAX_MATERIAL_UPLOAD_MB", "100")) * 1024 * 1024
_LOCK = threading.RLock()


class DuplicateMaterialError(ValueError):
    pass


def _ensure_root() -> None:
    MATERIAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _material_dir(file_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", file_id):
        raise ValueError("材料ID格式不正确")
    return MATERIAL_UPLOAD_DIR / file_id


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.2f} MB"


def list_materials(process: Optional[str] = None) -> list[dict[str, Any]]:
    _ensure_root()
    output: list[dict[str, Any]] = []
    with _LOCK:
        for directory in MATERIAL_UPLOAD_DIR.iterdir():
            metadata_file = directory / "meta.json"
            if not directory.is_dir() or not metadata_file.exists():
                continue
            try:
                metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if process and metadata.get("process") != process:
                continue
            output.append(metadata)
    return sorted(output, key=lambda item: (item.get("uploaded_at", 0), item.get("file_id", "")), reverse=True)


def find_duplicate(
    original_name: str,
    material_type: Optional[str],
    process: str,
) -> Optional[dict[str, Any]]:
    return next(
        (
            item
            for item in list_materials(process)
            if item.get("original_name") == original_name
            and (material_type is None or item.get("material_type") == material_type)
        ),
        None,
    )


def begin_material_upload(original_name: str, process: str, material_type: Optional[str] = None) -> tuple[dict[str, Any], Path]:
    safe_name = Path(original_name).name
    effective_type = material_type or guess_material_type(safe_name)
    with _LOCK:
        if find_duplicate(safe_name, effective_type if material_type else None, process):
            raise DuplicateMaterialError(f"该文件（{safe_name}）已存在于当前流程，不允许重复添加")
        file_id = uuid.uuid4().hex[:12]
        directory = _material_dir(file_id)
        directory.mkdir(parents=True, exist_ok=False)
        suffix = Path(safe_name).suffix.lower()
        staging_path = directory / f"original{suffix}.part"
        metadata = {
            "file_id": file_id,
            "original_name": safe_name,
            "size_bytes": 0,
            "size_human": "0 B",
            "material_type": effective_type,
            "process": process,
            "uploaded_at": int(time.time()),
            "parse_status": "上传中",
            "parse_error": None,
            "segments_count": 0,
            "file_kind": "unknown",
            "parser_profile": "",
            "template_version": "",
            "request_type": "",
            "mapping_version": "",
            "parse_warnings": [],
        }
        _atomic_write_json(directory / "meta.json", metadata)
        return metadata, staging_path


def finish_material_upload(file_id: str, staging_path: Path, size_bytes: int) -> dict[str, Any]:
    with _LOCK:
        metadata = load_material_meta(file_id)
        if metadata is None:
            raise FileNotFoundError(f"材料 {file_id} 不存在")
        final_path = staging_path.with_suffix("")
        os.replace(staging_path, final_path)
        metadata.update(
            {
                "size_bytes": size_bytes,
                "size_human": _human_size(size_bytes),
                "parse_status": "解析中",
                "parse_error": None,
            }
        )
        _atomic_write_json(_material_dir(file_id) / "meta.json", metadata)

    try:
        extracted = parse_material(
            final_path,
            metadata["material_type"],
            metadata["process"],
        )
        extracted.material_name = metadata["original_name"]
        extracted.size_bytes = size_bytes
        _atomic_write_json(_material_dir(file_id) / "extracted.json", extracted.model_dump(mode="json"))
        metadata.update(
            {
                "parse_status": "已解析",
                "segments_count": len(extracted.segments),
                "file_kind": extracted.file_kind,
                "material_type": extracted.material_type,
                "parser_profile": extracted.parser_profile,
                "template_version": extracted.template_version,
                "request_type": extracted.request_type,
                "mapping_version": extracted.mapping_version,
                "parse_warnings": extracted.parse_warnings,
            }
        )
    except Exception as error:
        metadata.update(
            {
                "parse_status": "解析失败",
                "parse_error": str(error),
                "segments_count": 0,
                "file_kind": "unknown",
            }
        )
    with _LOCK:
        _atomic_write_json(_material_dir(file_id) / "meta.json", metadata)
    return metadata


def abort_material_upload(file_id: str) -> None:
    with _LOCK:
        shutil.rmtree(_material_dir(file_id), ignore_errors=True)


def load_material_meta(file_id: str) -> Optional[dict[str, Any]]:
    metadata_file = _material_dir(file_id) / "meta.json"
    if not metadata_file.exists():
        return None
    try:
        return json.loads(metadata_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_extracted_material(file_id: str) -> Optional[ExtractedMaterial]:
    extracted_file = _material_dir(file_id) / "extracted.json"
    if not extracted_file.exists():
        return None
    try:
        return ExtractedMaterial.model_validate_json(extracted_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def delete_material(file_id: str) -> bool:
    directory = _material_dir(file_id)
    if not directory.exists():
        return False
    with _LOCK:
        shutil.rmtree(directory)
    return True


def resolve_review_materials(file_ids: list[str], process: str) -> list[ExtractedMaterial]:
    materials: list[ExtractedMaterial] = []
    for file_id in file_ids:
        metadata = load_material_meta(file_id)
        if metadata is None:
            raise FileNotFoundError(f"材料 {file_id} 不存在")
        if metadata.get("process") != process:
            raise ValueError(f"材料 {file_id} 不属于当前登记流程")
        if metadata.get("parse_status") != "已解析":
            reason = metadata.get("parse_error") or metadata.get("parse_status") or "未知原因"
            raise RuntimeError(f"材料 {metadata.get('original_name') or file_id} 尚未解析成功：{reason}")
        material = load_extracted_material(file_id)
        if material is None:
            raise RuntimeError(f"材料 {metadata.get('original_name') or file_id} 的解析结果不存在")
        if material.size_bytes is None:
            material.size_bytes = int(metadata.get("size_bytes") or 0)
        materials.append(material)
    return materials
