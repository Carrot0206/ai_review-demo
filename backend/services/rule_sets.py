"""上传规则版本存储。"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .rule_set_importer import import_rule_package_from_excel
from .schemas import ProcessType, Rule, TableScopeRule

RULE_SETS_DIR = Path(__file__).resolve().parent.parent / "data" / "rule_sets"
RULE_SETS_DIR.mkdir(parents=True, exist_ok=True)
INDEX_FILE = RULE_SETS_DIR / "index.json"


class RuleSetMeta(BaseModel):
    rule_set_id: str
    process: ProcessType
    filename: str
    created_at: int
    active: bool = False
    total_rules: int = 0
    script_count: int = 0
    ai_count: int = 0
    unsupported_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    scope_count: int = 0
    report: dict = Field(default_factory=dict)


def _load_index() -> list[RuleSetMeta]:
    if not INDEX_FILE.exists():
        return []
    raw = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return [RuleSetMeta.model_validate(item) for item in raw.get("rule_sets", [])]


def _save_index(items: list[RuleSetMeta]) -> None:
    INDEX_FILE.write_text(
        json.dumps({"rule_sets": [item.model_dump() for item in items]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _rule_set_dir(rule_set_id: str) -> Path:
    return RULE_SETS_DIR / rule_set_id


def list_rule_sets(process: Optional[ProcessType] = None) -> list[RuleSetMeta]:
    items = _load_index()
    if process:
        items = [item for item in items if item.process == process]
    return sorted(items, key=lambda x: x.created_at, reverse=True)


def get_active_rule_set(process: ProcessType) -> Optional[RuleSetMeta]:
    for item in list_rule_sets(process):
        if item.active:
            return item
    return None


def get_rule_set(rule_set_id: str) -> Optional[RuleSetMeta]:
    for item in _load_index():
        if item.rule_set_id == rule_set_id:
            return item
    return None


def load_rule_set_rules(rule_set_id: str) -> list[Rule]:
    path = _rule_set_dir(rule_set_id) / "rules.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Rule.model_validate(item) for item in raw.get("rules", [])]


def load_rule_set_scopes(rule_set_id: str) -> list[TableScopeRule]:
    path = _rule_set_dir(rule_set_id) / "table_scopes.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [TableScopeRule.model_validate(item) for item in raw.get("scopes", [])]


def create_rule_set(*, process: ProcessType, filename: str, content: bytes) -> RuleSetMeta:
    rules, scopes, report = import_rule_package_from_excel(content, filename=filename, process=process)
    now = int(time.time())
    rule_set_id = f"{process}_{now}_{uuid.uuid4().hex[:6]}"
    target = _rule_set_dir(rule_set_id)
    target.mkdir(parents=True, exist_ok=True)
    (target / "source.xlsx").write_bytes(content)
    (target / "rules.json").write_text(
        json.dumps({"rules": [r.model_dump() for r in rules]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target / "table_scopes.json").write_text(
        json.dumps({"scopes": [scope.model_dump() for scope in scopes]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = RuleSetMeta(
        rule_set_id=rule_set_id,
        process=process,
        filename=filename,
        created_at=now,
        active=False,
        total_rules=report["total_rules"],
        script_count=report["script_count"],
        ai_count=report["ai_count"],
        unsupported_count=report["unsupported_count"],
        error_count=report["error_count"],
        warning_count=report["warning_count"],
        scope_count=report.get("scope_count", 0),
        report=report,
    )
    items = _load_index()
    items.append(meta)
    _save_index(items)
    return meta


def activate_rule_set(rule_set_id: str) -> RuleSetMeta | None:
    items = _load_index()
    target = next((item for item in items if item.rule_set_id == rule_set_id), None)
    if not target:
        return None
    for item in items:
        if item.process == target.process:
            item.active = item.rule_set_id == rule_set_id
    _save_index(items)
    return next(item for item in items if item.rule_set_id == rule_set_id)


def delete_rule_set(rule_set_id: str) -> RuleSetMeta | None:
    items = _load_index()
    target = next((item for item in items if item.rule_set_id == rule_set_id), None)
    if not target:
        return None
    remaining = [item for item in items if item.rule_set_id != rule_set_id]
    _save_index(remaining)
    target_dir = _rule_set_dir(rule_set_id)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    return target


def resolve_rule_set_id(process: ProcessType, rule_set_id: str | None) -> str | None:
    if rule_set_id:
        meta = get_rule_set(rule_set_id)
        if meta and meta.process == process:
            return rule_set_id
        return None
    active = get_active_rule_set(process)
    return active.rule_set_id if active else None
