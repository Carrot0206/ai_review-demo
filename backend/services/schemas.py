"""共享数据结构。AI 审核结果 schema 与前端约定一致。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

RiskLevel = Literal["高风险", "中风险", "低风险"]
ProcessType = Literal["pre_report", "initial"]

PROCESS_LABEL = {
    "pre_report": "事前报告",
    "initial": "初始登记",
}


class Rule(BaseModel):
    """规则库中的一条规则（精简版，只保留 AI 审核需要的字段）。"""

    rule_id: str
    registration_type: str
    rule_source: str = "内置规则"
    source_file: str = ""
    source_sheet: str = ""
    source_row: int = 0
    rule_name: str
    rule_text: str
    basis_file: str = ""
    basis_text: str = ""
    review_dimension: str = ""
    table_name: str = ""
    field_name: str = ""
    applicable_materials: list[str] = Field(default_factory=list)
    review_method: str = "ai"
    check_type: str = ""
    trigger_condition: str = ""
    machine_params: str = ""
    risk_level: RiskLevel = "中风险"
    ai_check_focus: list[str] = Field(default_factory=list)
    evidence_requirement: str = ""
    enabled: bool = True
    demo_enabled: bool = True
    # 标记是否需要人工复核（版式/显著位置类规则不进 AI 批次）
    needs_human: bool = False


class MaterialSegment(BaseModel):
    """材料的一个文本片段，统一位置坐标供模型引用。"""

    location: str  # 例如 "第2页"、"产品基本信息表.信托业务分类"、"第3段"
    text: str


class ExtractedMaterial(BaseModel):
    """解析后的材料。"""

    material_name: str  # 原始文件名
    material_type: str  # 申请书/模板/信托文件样本/其他附件
    file_kind: Literal["json", "pdf", "docx", "txt", "unknown"]
    segments: list[MaterialSegment] = Field(default_factory=list)


class IssueLocation(BaseModel):
    material_name: str
    location: str
    value: str = ""


class RuleBasis(BaseModel):
    basis_type: Literal["内置规则", "用户新增规则"] = "内置规则"
    basis_file: str = ""
    rule_text: str = ""


class Issue(BaseModel):
    issue_id: str
    rule_id: str  # 主命中规则（向后兼容；合并后取首条）
    review_dimension: str = ""  # 主命中规则所属审核维度，用于前端按规则类别归组
    issue_summary: str
    risk_level: RiskLevel
    rule_basis: RuleBasis  # 主规则的依据（向后兼容）
    issue_location: list[IssueLocation] = Field(default_factory=list)
    suggestion: str = ""
    # 合并字段：当多条规则共同命中同一事实错误时，这里给出全部 rule_id / 规则依据 / 各自摘要与建议
    rule_ids: list[str] = Field(default_factory=list)
    rule_dimensions: list[str] = Field(default_factory=list)
    rule_bases: list[RuleBasis] = Field(default_factory=list)
    alt_summaries: list[str] = Field(default_factory=list)
    alt_suggestions: list[str] = Field(default_factory=list)


class ReviewSummary(BaseModel):
    registration_type: str
    total_issues: int = 0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0


class HumanReviewItem(BaseModel):
    """需人工复核的规则项（不进 AI 批次，不计入风险统计）。"""

    rule_id: str
    rule_name: str
    rule_text: str
    reason: str  # 为什么需要人工，例如 "版式/显著位置类，AI 不可靠"


class BatchLog(BaseModel):
    """单批次调用日志，用于过程日志面板。"""

    batch_id: str
    review_dimension: str
    rule_count: int
    status: Literal["success", "failed"]
    issues_found: int = 0
    duration_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: Optional[str] = None
    materials_used: list[str] = Field(default_factory=list)
    slice_enabled: bool = False
    slice_summary: str = ""
    original_segment_count: int = 0
    sliced_segment_count: int = 0
    slice_fallback: bool = False
    slice_confidence: str = ""


class ReviewResult(BaseModel):
    summary: ReviewSummary
    issues: list[Issue] = Field(default_factory=list)
    deduped_summary: Optional[ReviewSummary] = None
    deduped_issues: list[Issue] = Field(default_factory=list)
    human_review_items: list[HumanReviewItem] = Field(default_factory=list)
    batch_logs: list[BatchLog] = Field(default_factory=list)
