"""剧本模式：把 backend/samples/ 下的样例文件"一键导入"为上传材料。

注意：导入后仍走完整真实审核流程；不返回任何预写假结果。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.material_parser import guess_material_type
from ..services.upload_store import find_duplicate, reparse_upload, save_upload

router = APIRouter(prefix="/api/samples", tags=["samples"])

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

# 文件名关键字 → 所属流程
PROCESS_KEYWORDS = {
    "pre_report": ["事前报告", "事前报告模板", "事前报告申请书"],
    "initial": ["初始登记", "初始登记模板", "初始登记申请书", "信托文件样本"],
    "pre_registration_reapply": ["重新申请预登记"],
    "pre_registration": ["预登记", "预登记模板", "预登记申请书"],
    "termination": ["终止登记", "终止登记模板", "终止登记申请书", "清算报告"],
}


def _classify_file(name: str) -> Optional[str]:
    if "事前报告" in name:
        return "pre_report"
    if "重新申请预登记" in name:
        return "pre_registration_reapply"
    if "预登记" in name:
        return "pre_registration"
    if "初始登记" in name:
        return "initial"
    if "信托文件" in name:
        return "initial"
    if "终止登记" in name or "清算报告" in name:
        return "termination"
    return None


@router.get("")
def list_samples():
    """按流程列出 samples/ 下的所有样例文件。"""
    groups: dict[str, list[dict]] = {
        "pre_report": [],
        "initial": [],
        "pre_registration_reapply": [],
        "pre_registration": [],
        "termination": [],
    }
    if not SAMPLES_DIR.exists():
        return groups
    for p in sorted(SAMPLES_DIR.iterdir()):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in {".json", ".pdf", ".docx", ".txt", ".xlsx", ".xlsm"}:
            continue
        process = _classify_file(p.name)
        if process is None:
            continue
        groups[process].append(
            {
                "name": p.name,
                "size_bytes": p.stat().st_size,
                "material_type": guess_material_type(p.name),
            }
        )
    return groups


class SampleLoad(BaseModel):
    process: Literal[
        "pre_report",
        "initial",
        "pre_registration",
        "pre_registration_reapply",
        "termination",
    ]


@router.post("/load")
def load_samples(payload: SampleLoad):
    """把样例文件"假装上传"——读取本地文件并按上传流程保存+解析。

    返回新生成的 file_id 列表，前端可直接用于发起审核。
    同流程下已存在同名+同类型的样例会被跳过并在 skipped 中返回。
    """
    if not SAMPLES_DIR.exists():
        raise HTTPException(status_code=404, detail="samples 目录不存在")
    loaded: list[dict] = []
    skipped: list[dict] = []
    for p in sorted(SAMPLES_DIR.iterdir()):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in {".json", ".pdf", ".docx", ".txt", ".xlsx", ".xlsm"}:
            continue
        if _classify_file(p.name) != payload.process:
            continue
        mtype = guess_material_type(p.name)
        dup = find_duplicate(
            original_name=p.name,
            material_type=mtype,
            process=payload.process,
        )
        if dup is not None:
            if dup.get("parse_status") != "已解析":
                reparsed = reparse_upload(dup["file_id"]) or dup
                loaded.append(reparsed)
                continue
            skipped.append({"name": p.name, "reason": "已存在，跳过"})
            continue
        meta = save_upload(
            original_name=p.name,
            content=p.read_bytes(),
            material_type=mtype,
            process=payload.process,
        )
        loaded.append(meta)
    if not loaded and not skipped:
        raise HTTPException(
            status_code=404,
            detail=f"未在 samples/ 下找到流程={payload.process} 的样例文件",
        )
    return {"process": payload.process, "files": loaded, "skipped": skipped}
