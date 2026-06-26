"""上传文件存储 & 已解析材料缓存。

uploads/<file_id>/
    original.<ext>      原始文件
    meta.json           {file_id, original_name, size, material_type, parse_status, ...}
    extracted.json      ExtractedMaterial（解析后文本，供 review 复用）
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from .material_parser import guess_material_type, parse_material
from .schemas import ExtractedMaterial

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


def _file_dir(file_id: str) -> Path:
    return UPLOADS_DIR / file_id


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.2f} MB"


def save_upload(
    *,
    original_name: str,
    content: bytes,
    material_type: Optional[str] = None,
    process: Optional[str] = None,
) -> dict:
    """保存上传文件并立即解析。返回文件元信息字典。"""
    file_id = uuid.uuid4().hex[:12]
    fdir = _file_dir(file_id)
    fdir.mkdir(parents=True, exist_ok=True)

    suffix = Path(original_name).suffix.lower()
    original_path = fdir / f"original{suffix}"
    original_path.write_bytes(content)

    meta: dict = {
        "file_id": file_id,
        "original_name": original_name,
        "size_bytes": len(content),
        "size_human": _human_size(len(content)),
        "material_type": material_type or guess_material_type(original_name),
        "process": process,  # pre_report | initial | None（兼容旧上传）
        "uploaded_at": int(time.time()),
        "parse_status": "解析中",
        "parse_error": None,
        "segments_count": 0,
    }

    try:
        extracted = parse_material(original_path, meta["material_type"])
        # 把原文件名写入 ExtractedMaterial（avoid 用 original.json 这种内部名）
        extracted.material_name = original_name
        (fdir / "extracted.json").write_text(
            json.dumps(extracted.model_dump(), ensure_ascii=False),
            encoding="utf-8",
        )
        meta["parse_status"] = "已解析"
        meta["segments_count"] = len(extracted.segments)
        meta["file_kind"] = extracted.file_kind
    except Exception as e:
        meta["parse_status"] = "解析失败"
        meta["parse_error"] = str(e)

    (fdir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def load_meta(file_id: str) -> Optional[dict]:
    p = _file_dir(file_id) / "meta.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def load_extracted(file_id: str) -> Optional[ExtractedMaterial]:
    p = _file_dir(file_id) / "extracted.json"
    if not p.exists():
        return None
    return ExtractedMaterial.model_validate(json.loads(p.read_text(encoding="utf-8")))


def delete_upload(file_id: str) -> bool:
    fdir = _file_dir(file_id)
    if not fdir.exists():
        return False
    shutil.rmtree(fdir)
    return True


def list_uploads() -> list[dict]:
    out = []
    for d in sorted(UPLOADS_DIR.iterdir()):
        if d.is_dir() and (d / "meta.json").exists():
            out.append(json.loads((d / "meta.json").read_text(encoding="utf-8")))
    return out


def find_duplicate(
    *,
    original_name: str,
    material_type: Optional[str],
    process: Optional[str],
) -> Optional[dict]:
    """按 (process, original_name, material_type) 判重，返回已存在的 meta，否则 None。"""
    for m in list_uploads():
        if m.get("process") != process:
            continue
        if m.get("original_name") != original_name:
            continue
        if (m.get("material_type") or None) != (material_type or None):
            continue
        return m
    return None
