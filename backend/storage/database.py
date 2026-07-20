from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..models.schemas import BatchLog, ExtractedMaterial, Issue, RuleExecutionResult, RuleSnapshot


DB_PATH = Path(
    os.getenv(
        "RULE_ENGINE_DB_FILE",
        Path(__file__).resolve().parent.parent / "data" / "rule_engine.db",
    )
)
AI_TRACE_RETENTION_DAYS = int(os.getenv("AI_TRACE_RETENTION_DAYS", "7"))
_LOCK = threading.RLock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_db() -> None:
    with _LOCK, _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY,
                process TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                model_config_json TEXT NOT NULL,
                rules_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                process TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                status TEXT NOT NULL,
                materials_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL,
                error TEXT NOT NULL DEFAULT '',
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(snapshot_id) REFERENCES snapshots(snapshot_id)
            );
            CREATE TABLE IF NOT EXISTS rule_results (
                task_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                status TEXT NOT NULL,
                execution_method TEXT NOT NULL,
                result_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(task_id, rule_id),
                FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS issues (
                task_id TEXT NOT NULL,
                issue_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                issue_json TEXT NOT NULL,
                PRIMARY KEY(task_id, issue_id),
                FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS batches (
                task_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                status TEXT NOT NULL,
                execution_method TEXT NOT NULL,
                rule_ids_json TEXT NOT NULL,
                request_json TEXT NOT NULL,
                log_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(task_id, batch_id),
                FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS ai_traces (
                task_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                request_json TEXT NOT NULL,
                response_text TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY(task_id, batch_id),
                FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, event_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            """
        )


def mark_running_interrupted() -> int:
    now = time.time()
    with _LOCK, _connect() as connection:
        cursor = connection.execute(
            "UPDATE tasks SET status='interrupted', finished_at=?, error=? WHERE status IN ('queued','running')",
            (now, "服务重启导致任务中断"),
        )
        return cursor.rowcount


def cleanup_ai_traces() -> int:
    cutoff = time.time() - max(1, AI_TRACE_RETENTION_DAYS) * 86400
    with _LOCK, _connect() as connection:
        cursor = connection.execute("DELETE FROM ai_traces WHERE created_at < ?", (cutoff,))
        return cursor.rowcount


def create_task(task_id: str, snapshot: RuleSnapshot, materials: list[ExtractedMaterial]) -> None:
    with _LOCK, _connect() as connection:
        connection.execute(
            "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot.snapshot_id,
                snapshot.process,
                snapshot.sha256,
                snapshot.prompt_version,
                json.dumps(snapshot.model_config_snapshot, ensure_ascii=False),
                json.dumps([rule.model_dump() for rule in snapshot.rules], ensure_ascii=False),
                snapshot.created_at,
            ),
        )
        connection.execute(
            "INSERT INTO tasks(task_id,process,snapshot_id,status,materials_json,created_at) VALUES(?,?,?,?,?,?)",
            (
                task_id,
                snapshot.process,
                snapshot.snapshot_id,
                "queued",
                json.dumps([material.model_dump() for material in materials], ensure_ascii=False),
                time.time(),
            ),
        )


def set_task_status(task_id: str, status: str, error: str = "") -> None:
    now = time.time()
    fields = ["status=?", "error=?"]
    values: list[Any] = [status, error]
    if status == "running":
        fields.append("started_at=COALESCE(started_at, ?)")
        values.append(now)
    if status in {"done", "partial_failed", "failed", "cancelled", "interrupted"}:
        fields.append("finished_at=?")
        values.append(now)
    values.append(task_id)
    with _LOCK, _connect() as connection:
        connection.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE task_id=?", values)


def request_cancel(task_id: str) -> None:
    with _LOCK, _connect() as connection:
        connection.execute("UPDATE tasks SET cancel_requested=1 WHERE task_id=?", (task_id,))


def reset_task_for_retry(task_id: str) -> None:
    with _LOCK, _connect() as connection:
        connection.execute(
            "UPDATE tasks SET status='queued', cancel_requested=0, error='', finished_at=NULL WHERE task_id=?",
            (task_id,),
        )


def is_cancel_requested(task_id: str) -> bool:
    row = get_task_row(task_id)
    return bool(row and row["cancel_requested"])


def get_task_row(task_id: str) -> dict[str, Any] | None:
    with _LOCK, _connect() as connection:
        row = connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def get_snapshot(snapshot_id: str) -> RuleSnapshot | None:
    from ..services.rule_library import LibraryRule

    with _LOCK, _connect() as connection:
        row = connection.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
    if not row:
        return None
    return RuleSnapshot(
        snapshot_id=row["snapshot_id"],
        process=row["process"],
        sha256=row["sha256"],
        prompt_version=row["prompt_version"],
        model_config_snapshot=json.loads(row["model_config_json"]),
        rules=[LibraryRule.model_validate(item) for item in json.loads(row["rules_json"])],
        created_at=row["created_at"],
    )


def get_task_materials(task_id: str) -> list[ExtractedMaterial]:
    row = get_task_row(task_id)
    if not row:
        return []
    return [ExtractedMaterial.model_validate(item) for item in json.loads(row["materials_json"])]


def save_rule_result(task_id: str, result: RuleExecutionResult) -> None:
    with _LOCK, _connect() as connection:
        connection.execute(
            """INSERT INTO rule_results VALUES(?,?,?,?,?,?)
            ON CONFLICT(task_id,rule_id) DO UPDATE SET
              status=excluded.status,
              execution_method=excluded.execution_method,
              result_json=excluded.result_json,
              updated_at=excluded.updated_at""",
            (
                task_id,
                result.rule_id,
                result.status,
                result.execution_method,
                result.model_dump_json(),
                time.time(),
            ),
        )


def load_rule_results(task_id: str) -> list[RuleExecutionResult]:
    with _LOCK, _connect() as connection:
        rows = connection.execute(
            "SELECT result_json FROM rule_results WHERE task_id=? ORDER BY rule_id", (task_id,)
        ).fetchall()
    return [RuleExecutionResult.model_validate_json(row["result_json"]) for row in rows]


def replace_issues(task_id: str, issues: list[Issue]) -> None:
    with _LOCK, _connect() as connection:
        connection.execute("DELETE FROM issues WHERE task_id=?", (task_id,))
        connection.executemany(
            "INSERT INTO issues VALUES(?,?,?,?)",
            [(task_id, issue.issue_id, issue.rule_id, issue.model_dump_json()) for issue in issues],
        )


def load_issues(task_id: str) -> list[Issue]:
    with _LOCK, _connect() as connection:
        rows = connection.execute(
            "SELECT issue_json FROM issues WHERE task_id=? ORDER BY issue_id", (task_id,)
        ).fetchall()
    return [Issue.model_validate_json(row["issue_json"]) for row in rows]


def save_batch(task_id: str, log: BatchLog, request_payload: dict[str, Any]) -> None:
    with _LOCK, _connect() as connection:
        connection.execute(
            """INSERT INTO batches VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(task_id,batch_id) DO UPDATE SET
              status=excluded.status,
              log_json=excluded.log_json,
              request_json=excluded.request_json,
              updated_at=excluded.updated_at""",
            (
                task_id,
                log.batch_id,
                log.status,
                log.execution_method,
                json.dumps(log.rule_ids, ensure_ascii=False),
                json.dumps(request_payload, ensure_ascii=False),
                log.model_dump_json(),
                time.time(),
            ),
        )


def load_batches(task_id: str) -> list[BatchLog]:
    with _LOCK, _connect() as connection:
        rows = connection.execute(
            "SELECT log_json FROM batches WHERE task_id=? ORDER BY batch_id", (task_id,)
        ).fetchall()
    return [BatchLog.model_validate_json(row["log_json"]) for row in rows]


def load_failed_batch_rule_ids(task_id: str) -> set[str]:
    with _LOCK, _connect() as connection:
        rows = connection.execute(
            "SELECT rule_ids_json FROM batches WHERE task_id=? AND status='failed'", (task_id,)
        ).fetchall()
    return {rule_id for row in rows for rule_id in json.loads(row["rule_ids_json"])}


def clear_failed_batches(task_id: str) -> None:
    with _LOCK, _connect() as connection:
        connection.execute("DELETE FROM batches WHERE task_id=? AND status='failed'", (task_id,))


def delete_rule_results(task_id: str, rule_ids: set[str]) -> None:
    if not rule_ids:
        return
    placeholders = ",".join("?" for _ in rule_ids)
    with _LOCK, _connect() as connection:
        connection.execute(
            f"DELETE FROM rule_results WHERE task_id=? AND rule_id IN ({placeholders})",
            [task_id, *sorted(rule_ids)],
        )


def save_ai_trace(
    task_id: str,
    batch_id: str,
    request_payload: dict[str, Any],
    response_text: str,
    response_payload: dict[str, Any],
) -> None:
    with _LOCK, _connect() as connection:
        connection.execute(
            """INSERT INTO ai_traces VALUES(?,?,?,?,?,?)
            ON CONFLICT(task_id,batch_id) DO UPDATE SET
              request_json=excluded.request_json,
              response_text=excluded.response_text,
              response_json=excluded.response_json,
              created_at=excluded.created_at""",
            (
                task_id,
                batch_id,
                json.dumps(request_payload, ensure_ascii=False),
                response_text,
                json.dumps(response_payload, ensure_ascii=False),
                time.time(),
            ),
        )


def add_event(task_id: str, event_type: str, data: dict[str, Any]) -> int:
    with _LOCK, _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO events(task_id,event_type,data_json,created_at) VALUES(?,?,?,?)",
            (task_id, event_type, json.dumps(data, ensure_ascii=False), time.time()),
        )
        return int(cursor.lastrowid)


def load_events(task_id: str, after_id: int = 0) -> list[dict[str, Any]]:
    with _LOCK, _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM events WHERE task_id=? AND event_id>? ORDER BY event_id",
            (task_id, after_id),
        ).fetchall()
    return [
        {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "data": json.loads(row["data_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]
