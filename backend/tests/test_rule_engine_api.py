from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import app
from backend.services import material_store, rule_library
from backend.services.review_engine import TASK_MANAGER
from backend.storage import database
from backend.tests.test_ai_executor import FakeClient


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class RuleEngineApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_library_file = rule_library.RULE_LIBRARY_FILE
        self.original_db_path = database.DB_PATH
        self.original_material_dir = material_store.MATERIAL_UPLOAD_DIR
        rule_library.RULE_LIBRARY_FILE = Path(self.temp_dir.name) / "rules.json"
        database.DB_PATH = Path(self.temp_dir.name) / "rule_engine.db"
        material_store.MATERIAL_UPLOAD_DIR = Path(self.temp_dir.name) / "materials"
        TASK_MANAGER.client_override = None
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        TASK_MANAGER.client_override = None
        self.client_context.__exit__(None, None, None)
        rule_library.RULE_LIBRARY_FILE = self.original_library_file
        database.DB_PATH = self.original_db_path
        material_store.MATERIAL_UPLOAD_DIR = self.original_material_dir
        self.temp_dir.cleanup()

    @staticmethod
    def material_payload(value="10"):
        return [
            {
                "material_name": "预登记申报模板.json",
                "material_type": "申报模板",
                "file_kind": "json",
                "segments": [{"location": "表.A", "text": value}],
            }
        ]

    @staticmethod
    def script_rule_payload():
        return {
            "rule_id": "ENGINE-SCRIPT-001",
            "rule_name": "A字段必填",
            "process": "pre_registration",
            "review_method": "script",
            "applicable_materials": ["预登记申报模板"],
            "rule_object": "字段",
            "table_name": "表",
            "field_path": "表.A",
            "review_dimension": "法定要素完整性",
            "trigger_condition": "",
            "rule_text": "A字段必须填写。",
            "basis_text": "测试依据。",
            "risk_level": "中风险",
            "version": "V1.0",
            "enabled": True,
            "remarks": "",
            "operator": "required",
            "script_params": {},
            "special_prompt": "",
        }

    @classmethod
    def ai_rule_payload(cls):
        payload = cls.script_rule_payload()
        payload.update(
            {
                "rule_id": "ENGINE-AI-001",
                "rule_name": "AI语义审核",
                "review_method": "ai",
                "operator": "",
                "script_params": {},
                "special_prompt": "严格依据规则内容判断。",
            }
        )
        return payload

    def wait_for_status(self, task_id, expected, timeout=3):
        deadline = time.time() + timeout
        while time.time() < deadline:
            payload = self.client.get(f"/api/rule-engine/reviews/{task_id}").json()
            if payload["status"] in expected:
                return payload
            time.sleep(0.02)
        self.fail(f"任务未在限定时间进入 {expected}")

    def test_empty_library_rejected_and_script_review_persists(self):
        empty = self.client.post(
            "/api/rule-engine/reviews",
            json={"process": "pre_registration", "materials": self.material_payload()},
        )
        self.assertEqual(empty.status_code, 409)

        created_rule = self.client.post("/api/rule-library/rules", json=self.script_rule_payload())
        self.assertEqual(created_rule.status_code, 200, created_rule.text)
        created = self.client.post(
            "/api/rule-engine/reviews",
            json={"process": "pre_registration", "materials": self.material_payload()},
        )
        self.assertEqual(created.status_code, 202, created.text)
        task_id = created.json()["task_id"]

        self.client.patch("/api/rule-library/rules/ENGINE-SCRIPT-001/enabled", json={"enabled": False})
        task = self.wait_for_status(task_id, {"done"})
        self.assertEqual(task["rule_count"], 1)
        self.assertEqual(task["status_counts"]["passed"], 1)
        snapshot = database.get_snapshot(task["snapshot_id"])
        self.assertTrue(snapshot.rules[0].enabled)

        result = self.client.get(f"/api/rule-engine/reviews/{task_id}/result")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["summary"]["conclusion"], "未发现问题")
        self.assertEqual(len(result.json()["rule_results"]), 1)

        events = self.client.get(f"/api/rule-engine/reviews/{task_id}/events")
        self.assertEqual(events.status_code, 200)
        self.assertIn("event: task_finished", events.text)

    def test_failed_ai_batch_can_retry_with_original_snapshot(self):
        self.assertEqual(self.client.post("/api/rule-library/rules", json=self.ai_rule_payload()).status_code, 200)
        TASK_MANAGER.client_override = FakeClient(invalid=True)
        created = self.client.post(
            "/api/rule-engine/reviews",
            json={"process": "pre_registration", "materials": self.material_payload()},
        )
        task_id = created.json()["task_id"]
        first = self.wait_for_status(task_id, {"partial_failed"}, timeout=5)
        self.assertEqual(first["status_counts"]["error"], 1)

        self.client.delete("/api/rule-library/rules/ENGINE-AI-001")
        TASK_MANAGER.client_override = FakeClient()
        retried = self.client.post(f"/api/rule-engine/reviews/{task_id}/retry-failed")
        self.assertEqual(retried.status_code, 202, retried.text)
        final = self.wait_for_status(task_id, {"done"}, timeout=5)
        self.assertEqual(final["status_counts"]["passed"], 1)
        result = self.client.get(f"/api/rule-engine/reviews/{task_id}/result").json()
        self.assertEqual(result["summary"]["conclusion"], "未发现问题")

    def test_startup_marks_running_tasks_interrupted(self):
        self.assertEqual(self.client.post("/api/rule-library/rules", json=self.script_rule_payload()).status_code, 200)
        snapshot_id = "snapshot-interrupted"
        task_id = "task-interrupted"
        from backend.services.review_engine import create_snapshot

        snapshot = create_snapshot("pre_registration").model_copy(update={"snapshot_id": snapshot_id})
        database.create_task(task_id, snapshot, [])
        database.set_task_status(task_id, "running")
        self.assertEqual(database.mark_running_interrupted(), 1)
        self.assertEqual(database.get_task_row(task_id)["status"], "interrupted")

    def test_stored_material_ids_create_review_and_validate_source(self):
        self.assertEqual(self.client.post("/api/rule-library/rules", json=self.script_rule_payload()).status_code, 200)
        uploaded = self.client.post(
            "/api/rule-engine/materials",
            data={"process": "pre_registration"},
            files={
                "file": (
                    "预登记申报模板.json",
                    '{"表":{"A":"10"}}'.encode("utf-8"),
                    "application/json",
                )
            },
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        file_id = uploaded.json()["file_id"]

        created = self.client.post(
            "/api/rule-engine/reviews",
            json={"process": "pre_registration", "file_ids": [file_id]},
        )
        self.assertEqual(created.status_code, 202, created.text)
        final = self.wait_for_status(created.json()["task_id"], {"done"})
        self.assertEqual(final["status_counts"]["passed"], 1)

        missing = self.client.post(
            "/api/rule-engine/reviews",
            json={"process": "pre_registration", "file_ids": ["000000000000"]},
        )
        self.assertEqual(missing.status_code, 404)
        mismatch = self.client.post(
            "/api/rule-engine/reviews",
            json={"process": "initial", "file_ids": [file_id]},
        )
        self.assertEqual(mismatch.status_code, 409)
        duplicate = self.client.post(
            "/api/rule-engine/reviews",
            json={"process": "pre_registration", "file_ids": [file_id, file_id]},
        )
        self.assertEqual(duplicate.status_code, 422)

        failed_upload = self.client.post(
            "/api/rule-engine/materials",
            data={"process": "pre_registration"},
            files={"file": ("损坏模板.json", b"invalid-json", "application/json")},
        )
        self.assertEqual(failed_upload.json()["parse_status"], "解析失败")
        failed_review = self.client.post(
            "/api/rule-engine/reviews",
            json={"process": "pre_registration", "file_ids": [failed_upload.json()["file_id"]]},
        )
        self.assertEqual(failed_review.status_code, 409)

    def test_actual_registration_export_runs_through_review_api(self):
        rule = self.script_rule_payload()
        rule.update(
            {
                "rule_id": "ENGINE-ACTUAL-001",
                "rule_name": "实际申报模板产品名称必填",
                "table_name": "1.产品基本信息",
                "field_path": "1.产品基本信息.信托产品全称",
            }
        )
        self.assertEqual(self.client.post("/api/rule-library/rules", json=rule).status_code, 200)
        uploaded = self.client.post(
            "/api/rule-engine/materials",
            data={"process": "pre_registration"},
            files={
                "file": (
                    "新预登记.json",
                    (PROJECT_ROOT / "申请模版json样例" / "新预登记.json").read_bytes(),
                    "application/json",
                )
            },
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["material_type"], "申报模板")
        created = self.client.post(
            "/api/rule-engine/reviews",
            json={
                "process": "pre_registration",
                "file_ids": [uploaded.json()["file_id"]],
            },
        )
        self.assertEqual(created.status_code, 202, created.text)
        final = self.wait_for_status(created.json()["task_id"], {"done"})
        self.assertEqual(final["status_counts"]["passed"], 1)


if __name__ == "__main__":
    unittest.main()
