from __future__ import annotations

import unittest
from datetime import date, timedelta
from pathlib import Path

from backend.executors.script_executor import execute_rule, execute_rules
from backend.models.schemas import ExtractedMaterial, MaterialSegment
from backend.services.rule_library import LibraryRule
from backend.services.material_parser import parse_material


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def make_rule(operator: str, params=None, field="表.A", rule_id=None) -> LibraryRule:
    return LibraryRule(
        rule_id=rule_id or f"TEST-{operator.replace('_', '-').upper()}",
        rule_name=f"{operator}测试规则",
        process="pre_registration",
        review_method="script",
        applicable_materials=["预登记申报模板"],
        rule_object="字段",
        table_name="表",
        field_path=field,
        review_dimension="法定要素完整性",
        trigger_condition="",
        rule_text="测试规则内容",
        basis_text="测试依据",
        risk_level="中风险",
        version="V1.0",
        enabled=True,
        remarks="",
        operator=operator,
        script_params=params or {},
        special_prompt="",
        source_file="",
        source_sheet="",
        source_row=0,
        created_at=1,
        updated_at=1,
    )


def materials() -> list[ExtractedMaterial]:
    tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    return [
        ExtractedMaterial(
            material_name="预登记申报模板.json",
            material_type="申报模板",
            file_kind="json",
            segments=[
                MaterialSegment(location="表.A", text="10"),
                MaterialSegment(location="表.B", text="20"),
                MaterialSegment(location="表.Required", text="已填写"),
                MaterialSegment(location="表.Enum", text="甲"),
                MaterialSegment(location="表.Long", text="abc"),
                MaterialSegment(location="表.Precision", text="1.23"),
                MaterialSegment(location="表.Date", text=tomorrow),
                MaterialSegment(location="表.Regex", text="ABC-12"),
                MaterialSegment(location="明细[0].Seq", text="1"),
                MaterialSegment(location="明细[1].Seq", text="2"),
                MaterialSegment(location="明细[0].Parent", text="P"),
                MaterialSegment(location="明细[0].Child", text="C"),
                MaterialSegment(location="明细[0].Group", text="G"),
                MaterialSegment(location="明细[0].Value", text="Z"),
                MaterialSegment(location="明细[1].Group", text="G"),
                MaterialSegment(location="明细[1].Value", text="Z"),
                MaterialSegment(location="表.Current", text="same"),
                MaterialSegment(location="表.Ref", text="R1"),
            ],
        ),
        ExtractedMaterial(
            material_name="历史模板.json",
            material_type="上一次登记申报模板",
            file_kind="json",
            segments=[MaterialSegment(location="表.Baseline", text="same")],
        ),
        ExtractedMaterial(
            material_name="营业执照.pdf",
            material_type="其他附件",
            file_kind="pdf",
            size_bytes=1024,
            segments=[MaterialSegment(location="正文", text="有效")],
        ),
    ]


class ScriptExecutorTest(unittest.TestCase):
    def test_all_nineteen_operators_can_pass(self):
        cases = [
            make_rule("required", field="表.Required"),
            make_rule("enum", {"values": ["甲", "乙"]}, "表.Enum"),
            make_rule("dependent_enum", {"parent_field": "Parent", "child_field": "Child", "mapping": {"P": ["C"]}}, "Child"),
            make_rule("max_length", {"max_length": 3}, "表.Long"),
            make_rule("number_precision", {"scale": 2}, "表.Precision"),
            make_rule("date_format", {}, "表.Date"),
            make_rule("date_range", {"min": "today", "max_days": 30}, "表.Date"),
            make_rule("regex_match", {"pattern": r"[A-Z]{3}-\d{2}"}, "表.Regex"),
            make_rule("sequence_contiguous", {"start": 1}, "Seq"),
            make_rule("compare_fields", {"right_field": "表.B", "relation": "lte"}, "表.A"),
            make_rule("cross_template_equal", {"current_field": "表.Current", "baseline_field": "表.Baseline"}, "表.Current"),
            make_rule("conditional_compare", {"trigger": {"field": "表.Required", "op": "not_blank"}, "target": {"field": "表.A", "op": "lte_field", "other_field": "表.B"}}),
            make_rule("material_required", {"material_label": "营业执照"}),
            make_rule("conditional_material_required", {"trigger": {"field": "表.Required", "op": "not_blank"}, "material_label": "营业执照"}),
            make_rule("unique", {"fields": ["Seq"]}, "Seq"),
            make_rule("reference_exists", {"reference_values": ["R1", "R2"]}, "表.Ref"),
            make_rule("formula_compare", {"expression": "表.A + 表.B", "relation": "equals", "expected_value": 30}),
            make_rule("group_consistency", {"group_by": "Group", "consistent_fields": ["Value"]}, "Group"),
            make_rule("compound_condition", {"conditions": [{"type": "numeric_range", "field": "表.A", "min": 0, "max": 20}]}),
        ]
        self.assertEqual(len(cases), 19)
        for rule in cases:
            with self.subTest(operator=rule.operator):
                result = execute_rule(rule, materials())
                self.assertEqual(result.status, "passed")

    def test_failures_missing_fields_and_invalid_parameters(self):
        failed_cases = [
            make_rule("required", field="表.Missing"),
            make_rule("enum", {"values": ["乙"]}, "表.Enum"),
            make_rule("max_length", {"max_length": 2}, "表.Long"),
            make_rule("number_precision", {"scale": 1}, "表.Precision"),
            make_rule("regex_match", {"pattern": r"\d+"}, "表.Regex"),
            make_rule("compare_fields", {"right_field": "表.B", "relation": "gte"}, "表.A"),
            make_rule("reference_exists", {"reference_values": ["R2"]}, "表.Ref"),
            make_rule("formula_compare", {"expression": "表.A + 表.B", "relation": "equals", "expected_value": 31}),
        ]
        for rule in failed_cases:
            with self.subTest(operator=rule.operator):
                self.assertEqual(execute_rule(rule, materials()).status, "failed")

        invalid = make_rule("enum", {}, "表.Enum", "TEST-INVALID-ENUM")
        missing_reference = make_rule("reference_exists", {}, "表.Ref", "TEST-MISSING-REFERENCE")
        results, fallback = execute_rules([invalid, missing_reference], materials())
        self.assertEqual(results, [])
        self.assertEqual({rule.rule_id for rule in fallback}, {invalid.rule_id, missing_reference.rule_id})

    def test_numbered_rule_path_matches_unnumbered_array_location(self):
        rule = make_rule(
            "required",
            field="4.底层资产及交易对手.交易对手信息",
            rule_id="TEST-NUMBERED-PATH",
        )
        result = execute_rule(rule, materials())
        self.assertEqual(result.status, "failed")

        source = materials()
        source[0].segments.append(
            MaterialSegment(location="底层资产及交易对手[0].交易对手信息", text="交易对手信息1")
        )
        result = execute_rule(rule, source)
        self.assertEqual(result.status, "passed")

    def test_blank_values_are_checked_only_by_presence_rules(self):
        blank_materials = [
            ExtractedMaterial(
                material_name="预登记申报模板.json",
                material_type="申报模板",
                file_kind="json",
                segments=[
                    MaterialSegment(location="表.Trigger", text="否"),
                    MaterialSegment(location="表.Optional", text=""),
                    MaterialSegment(location="表.Other", text=""),
                    MaterialSegment(location="明细[0].Parent", text="P"),
                    MaterialSegment(location="明细[0].Child", text=""),
                ],
            ),
            ExtractedMaterial(
                material_name="历史模板.json",
                material_type="上一次登记申报模板",
                file_kind="json",
                segments=[MaterialSegment(location="表.Baseline", text="")],
            ),
        ]
        optional_rules = [
            make_rule("enum", {"values": ["甲"], "selection_mode": "single"}, "表.Optional"),
            make_rule("dependent_enum", {"parent_field": "Parent", "child_field": "Child", "mapping": {"P": ["C"]}}, "Child"),
            make_rule("max_length", {"max_length": 3}, "表.Optional"),
            make_rule("number_precision", {"scale": 2}, "表.Optional"),
            make_rule("date_format", {}, "表.Optional"),
            make_rule("date_range", {"min": "today"}, "表.Optional"),
            make_rule("regex_match", {"pattern": r"\d+"}, "表.Optional"),
            make_rule("sequence_contiguous", {"start": 1}, "表.Optional"),
            make_rule("compare_fields", {"right_field": "表.Other", "relation": "lte"}, "表.Optional"),
            make_rule("cross_template_equal", {"current_field": "表.Optional", "baseline_field": "表.Baseline"}, "表.Optional"),
            make_rule("reference_exists", {"reference_values": ["甲"]}, "表.Optional"),
            make_rule(
                "conditional_compare",
                {"trigger": {"field": "表.Trigger", "op": "equals", "value": "是"}, "target": {"field": "表.Optional", "op": "required"}},
            ),
        ]
        for rule in optional_rules:
            with self.subTest(operator=rule.operator):
                self.assertEqual(execute_rule(rule, blank_materials).status, "not_applicable")

        required = make_rule("required", field="表.Optional")
        self.assertEqual(execute_rule(required, blank_materials).status, "failed")

        triggered_required = make_rule(
            "conditional_compare",
            {"trigger": {"field": "表.Trigger", "op": "equals", "value": "否"}, "target": {"field": "表.Optional", "op": "required"}},
        )
        self.assertEqual(execute_rule(triggered_required, blank_materials).status, "failed")

    def test_enum_ignores_blank_rows_but_validates_populated_rows(self):
        source = [
            ExtractedMaterial(
                material_name="预登记申报模板.json",
                material_type="申报模板",
                file_kind="json",
                segments=[
                    MaterialSegment(location="明细[0].类型", text=""),
                    MaterialSegment(location="明细[1].类型", text="甲"),
                ],
            )
        ]
        rule = make_rule("enum", {"values": ["甲", "乙"]}, "类型")
        self.assertEqual(execute_rule(rule, source).status, "passed")
        source[0].segments[1].text = "非法值"
        result = execute_rule(rule, source)
        self.assertEqual(result.status, "failed")
        self.assertEqual([item.location for item in result.evidence], ["明细[1].类型"])

    def test_actual_export_chinese_paths_match_script_rules(self):
        material = parse_material(
            PROJECT_ROOT / "申请模版json样例" / "新预登记.json",
            process="pre_registration",
        )
        required = make_rule("required", field="1.产品基本信息.信托产品全称")
        registration_type = make_rule(
            "enum",
            {"values": ["预登记", "初始登记"]},
            "1.产品基本信息.登记类型",
        )
        repeated_enum = make_rule(
            "enum",
            {"values": ["资金投向", "受托财产"]},
            "4.底层资产及交易对手.资产取得方式",
        )
        for rule in (required, registration_type, repeated_enum):
            with self.subTest(rule=rule.field_path):
                self.assertEqual(execute_rule(rule, [material]).status, "passed")

    def test_compound_condition_subtypes(self):
        checks = [
            {"type": "conditional_compare", "trigger": {"field": "表.Required", "op": "not_blank"}, "target": {"field": "表.A", "op": "lte_field", "other_field": "表.B"}},
            {"type": "conditional_enum", "trigger": {"field": "表.Required", "op": "not_blank"}, "field": "表.Enum", "values": ["甲"], "required": True},
            {"type": "dependent_enum", "parent_field": "Parent", "child_field": "Child", "mapping": {"P": ["C"]}},
            {"type": "numeric_range", "field": "表.A", "min": 0, "max": 20},
            {"type": "field_compare", "left_field": "表.A", "right_field": "表.B", "op": "lte"},
            {"type": "date_compare", "left_field": "表.Date", "right_field": "表.Date", "op": "lte"},
            {"type": "enum", "field": "表.Enum", "values": ["甲"]},
            {"type": "forbidden_combination", "field": "表.Enum", "values": ["甲", "乙"]},
            {"type": "conditional_blank", "trigger": {"field": "表.Required", "op": "not_blank"}, "target": {"field": "表.Missing", "op": "blank"}},
            {"type": "file_size_limit", "material_label": "营业执照", "max_mb": 1, "required": True},
            {"type": "text_format", "trim_required": True, "forbid_control_chars": True},
            {"type": "numeric_text_format", "forbid_plus_sign": True, "forbid_redundant_leading_zero": True},
            {"type": "number_precision", "field": "表.Precision", "scale": 2},
            {"type": "regex_match", "field": "表.Regex", "pattern": r"[A-Z]{3}-\d{2}"},
            {"type": "max_length", "field": "表.Long", "max_length": 3},
        ]
        for index, check in enumerate(checks):
            rule = make_rule("compound_condition", {"conditions": [check]}, rule_id=f"TEST-COMPOUND-{index:02d}")
            with self.subTest(subtype=check["type"]):
                self.assertEqual(execute_rule(rule, materials()).status, "passed")


if __name__ == "__main__":
    unittest.main()
