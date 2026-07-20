from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from ..models.schemas import ExtractedMaterial, MaterialSegment
from .rule_library import LibraryProcess


MAPPING_DIR = Path(__file__).resolve().parent.parent / "data" / "template_mappings"
PROCESS_BY_REQUEST_TYPE: dict[str, LibraryProcess] = {
    "0": "pre_registration",
    "9": "pre_report",
    "1": "initial",
    "4": "termination",
}
EXPORT_KEYS = {"version", "requestType", "trustCompanyId", "projectCount", "projectList"}


def load_json_document(path: Path) -> Any:
    text = path.read_text(encoding="utf-8-sig")
    text = re.sub(r"^[0-9a-fA-F]{32}(?=\s*\{)", "", text, count=1)
    return json.loads(text)


def is_registration_export(payload: Any) -> bool:
    return isinstance(payload, dict) and EXPORT_KEYS.issubset(payload.keys())


@lru_cache(maxsize=4)
def load_mapping(process: LibraryProcess) -> dict[str, Any]:
    path = MAPPING_DIR / f"{process}.json"
    if not path.exists():
        raise RuntimeError(f"登记模板映射不存在：{process}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("process") != process:
        raise RuntimeError(f"登记模板映射内容无效：{process}")
    return payload


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _normalize_date(value: str) -> str:
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%Y%m%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"日期值无法识别：{value}")


def _decode_value(field: dict[str, Any], raw_value: Any, record: dict[str, Any]) -> str:
    text = _text(raw_value)
    if not text:
        return ""
    values = field.get("values")
    if isinstance(values, dict):
        tokens = [text]
        if field.get("multiple"):
            tokens = [item.strip() for item in re.split(r"[,，、;；]", text) if item.strip()]
        unknown = [item for item in tokens if item not in values]
        if unknown:
            raise ValueError(f"字段“{field['name']}”包含未知枚举代码：{'、'.join(unknown)}")
        return "、".join(str(values[item]) for item in tokens)
    dependent_values = field.get("dependent_values")
    if isinstance(dependent_values, dict):
        parent_field = str(field.get("dependent_parent") or "")
        parent_value = _text(record.get(parent_field))
        mapping = dependent_values.get(parent_value)
        if not isinstance(mapping, dict) or text not in mapping:
            raise ValueError(
                f"字段“{field['name']}”包含未知联动枚举代码：parent={parent_value}, value={text}"
            )
        return str(mapping[text])
    if str(field.get("component_type")) == "4":
        return _normalize_date(text)
    return text


def _validate_single_project(payload: dict[str, Any]) -> dict[str, Any]:
    project_count = _text(payload.get("projectCount"))
    projects = payload.get("projectList")
    if not isinstance(projects, list):
        raise ValueError("实际登记模板的projectList必须为数组")
    if project_count != str(len(projects)):
        raise ValueError(f"projectCount={project_count} 与projectList数量 {len(projects)} 不一致")
    if len(projects) != 1:
        raise ValueError("当前版本一次只审核一个信托产品，请将多产品JSON拆分后分别上传")
    if not isinstance(projects[0], dict):
        raise ValueError("projectList中的产品数据必须为对象")
    return projects[0]


def parse_registration_export(
    path: Path,
    payload: dict[str, Any],
    requested_process: Optional[LibraryProcess] = None,
) -> ExtractedMaterial:
    request_type = _text(payload.get("requestType"))
    detected_process = PROCESS_BY_REQUEST_TYPE.get(request_type)
    if detected_process is None:
        raise ValueError(f"无法识别登记流程requestType：{request_type or '空'}")
    if requested_process and requested_process != detected_process:
        raise ValueError(
            f"申请模板属于 {detected_process}，与当前选择流程 {requested_process} 不一致"
        )
    mapping = load_mapping(detected_process)
    if _text(mapping.get("request_type")) != request_type:
        raise ValueError("登记模板映射与requestType不一致")
    project = _validate_single_project(payload)
    version = _text(payload.get("version"))
    supported_versions = [str(item) for item in mapping.get("supported_versions") or []]
    warnings: list[str] = []
    if version not in supported_versions:
        warnings.append(
            f"模板版本 {version or '空'} 未经验证，已按流程 {detected_process} 的最新映射兼容解析"
        )

    segments: list[MaterialSegment] = []
    containers = mapping.get("containers") or {}
    for container_code, raw_records in project.items():
        container = containers.get(container_code)
        if not isinstance(container, dict):
            raise ValueError(f"模板包含未知表代码：{container_code}")
        is_array = container.get("is_array") is True
        if is_array:
            if not isinstance(raw_records, list):
                raise ValueError(f"表 {container_code} 应为数组")
            records = raw_records
        else:
            if not isinstance(raw_records, dict):
                raise ValueError(f"表 {container_code} 应为对象")
            records = [raw_records]
        for record_index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(f"表 {container_code} 第{record_index + 1}条记录不是对象")
            for field_code, raw_value in record.items():
                field = (container.get("fields") or {}).get(field_code)
                if not isinstance(field, dict):
                    raise ValueError(f"模板包含未知字段代码：{container_code}.{field_code}")
                section = str(container.get("section") or field.get("section") or "").strip()
                if not section:
                    raise ValueError(f"字段 {container_code}.{field_code} 缺少中文分类")
                location = (
                    f"{section}[{record_index}].{field['name']}"
                    if is_array
                    else f"{section}.{field['name']}"
                )
                raw_location = (
                    f"projectList[0].{container_code}[{record_index}].{field_code}"
                    if is_array
                    else f"projectList[0].{container_code}.{field_code}"
                )
                segments.append(
                    MaterialSegment(
                        location=location,
                        text=_decode_value(field, raw_value, record),
                        raw_location=raw_location,
                        raw_text=_text(raw_value),
                    )
                )

    return ExtractedMaterial(
        material_name=path.name,
        material_type="申报模板",
        file_kind="json",
        segments=segments,
        parser_profile="registration_export_json",
        template_version=version,
        request_type=request_type,
        mapping_version=_text(mapping.get("mapping_version")),
        parse_warnings=warnings,
    )
