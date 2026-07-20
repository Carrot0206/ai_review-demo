from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import dataclass

from backend.executors.ai_executor import run_ai_rules
from backend.models.schemas import ExtractedMaterial, MaterialSegment
from backend.services.ai_client import AIResponse
from backend.tests.test_script_executor import make_rule


@dataclass
class FakeConfig:
    max_retries: int = 0


class FakeClient:
    def __init__(self, invalid=False):
        self.config = FakeConfig(max_retries=1 if invalid else 0)
        self.calls = 0
        self.active = 0
        self.peak = 0
        self.invalid = invalid

    async def chat(self, messages):
        self.calls += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.01)
        payload = json.loads(messages[-1]["content"])
        rule_ids = [rule["rule_id"] for rule in payload["rules"]]
        if self.invalid:
            rule_ids = rule_ids[:-1]
        parsed = {
            "results": [
                {"rule_id": rule_id, "status": "passed", "summary": "", "suggestion": "", "evidence": []}
                for rule_id in rule_ids
            ]
        }
        self.active -= 1
        return AIResponse(content=json.dumps(parsed), parsed=parsed, input_tokens=10, output_tokens=5)


class AIExecutorTest(unittest.IsolatedAsyncioTestCase):
    async def test_batch_size_concurrency_and_exact_results(self):
        rules = []
        for index in range(9):
            rule = make_rule("required", field="表.A", rule_id=f"AI-{index:03d}")
            rule = rule.model_copy(update={"review_method": "ai", "operator": "", "special_prompt": "按规则审核"})
            rules.append(rule)
        client = FakeClient()
        results, logs, failed = await run_ai_rules(
            task_id="TASK",
            process="pre_registration",
            rules=rules,
            materials=[ExtractedMaterial(material_name="模板.json", material_type="申报模板", file_kind="json", segments=[MaterialSegment(location="表.A", text="1")])],
            execution_method="ai",
            batch_prefix="AI-",
            client=client,
        )
        self.assertEqual([len(log.rule_ids) for log in logs], [4, 4, 1])
        self.assertEqual({result.rule_id for result in results}, {rule.rule_id for rule in rules})
        self.assertEqual(len(results), 9)
        self.assertEqual(failed, set())
        self.assertEqual(client.peak, 3)

    async def test_invalid_rule_id_set_retries_then_fails_batch(self):
        rules = []
        for index in range(2):
            rule = make_rule("required", field="表.A", rule_id=f"BAD-{index:03d}")
            rules.append(rule.model_copy(update={"review_method": "ai", "operator": "", "special_prompt": "按规则审核"}))
        client = FakeClient(invalid=True)
        results, logs, failed = await run_ai_rules(
            task_id="TASK",
            process="pre_registration",
            rules=rules,
            materials=[],
            execution_method="ai",
            batch_prefix="AI-",
            client=client,
        )
        self.assertEqual(results, [])
        self.assertEqual(logs[0].status, "failed")
        self.assertEqual(client.calls, 2)
        self.assertEqual(failed, {rule.rule_id for rule in rules})


if __name__ == "__main__":
    unittest.main()
