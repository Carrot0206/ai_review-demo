from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from ..services.rule_library import LibraryProcess, LibraryRule


TaskStatus = Literal[
    "queued",
    "running",
    "done",
    "partial_failed",
    "failed",
    "cancelled",
    "interrupted",
]
RuleStatus = Literal["passed", "failed", "not_applicable", "undetermined", "error"]
ExecutionMethod = Literal["script", "ai", "ai_fallback"]


class MaterialSegment(BaseModel):
    location: str
    text: str = ""
    raw_location: str = ""
    raw_text: str = ""


class ExtractedMaterial(BaseModel):
    material_name: str
    material_type: str
    file_kind: Literal["json", "pdf", "docx", "txt", "excel", "unknown"] = "unknown"
    size_bytes: Optional[int] = None
    segments: list[MaterialSegment] = Field(default_factory=list)
    parser_profile: str = ""
    template_version: str = ""
    request_type: str = ""
    mapping_version: str = ""
    parse_warnings: list[str] = Field(default_factory=list)


class ReviewStart(BaseModel):
    process: LibraryProcess
    materials: list[ExtractedMaterial] = Field(default_factory=list)
    file_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_material_source(self) -> "ReviewStart":
        if bool(self.materials) == bool(self.file_ids):
            raise ValueError("materials 与 file_ids 必须且只能提供一种")
        if len(self.file_ids) != len(set(self.file_ids)):
            raise ValueError("file_ids 不允许包含重复材料ID")
        return self


class RuleEvidence(BaseModel):
    material_name: str = ""
    location: str = ""
    value: str = ""


class RuleExecutionResult(BaseModel):
    rule_id: str
    status: RuleStatus
    execution_method: ExecutionMethod
    summary: str = ""
    suggestion: str = ""
    evidence: list[RuleEvidence] = Field(default_factory=list)
    error: str = ""
    batch_id: str = ""
    duration_seconds: float = 0.0


class RuleBasis(BaseModel):
    basis_type: str = "规则库规则"
    basis_file: str = ""
    rule_text: str = ""


class Issue(BaseModel):
    issue_id: str
    rule_id: str
    review_dimension: str
    issue_summary: str
    risk_level: str
    rule_basis: RuleBasis
    issue_location: list[RuleEvidence] = Field(default_factory=list)
    suggestion: str = ""
    execution_method: ExecutionMethod
    rule_ids: list[str] = Field(default_factory=list)
    rule_dimensions: list[str] = Field(default_factory=list)
    rule_bases: list[RuleBasis] = Field(default_factory=list)


class BatchLog(BaseModel):
    batch_id: str
    execution_method: Literal["ai", "ai_fallback"]
    review_dimension: str
    rule_ids: list[str]
    status: Literal["running", "success", "failed", "cancelled"]
    duration_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    materials_used: list[str] = Field(default_factory=list)
    error: str = ""
    attempts: int = 0


class RuleSnapshot(BaseModel):
    snapshot_id: str
    process: LibraryProcess
    sha256: str
    prompt_version: str
    model_config_snapshot: dict[str, Any]
    rules: list[LibraryRule]
    created_at: float


class ReviewSummary(BaseModel):
    process: LibraryProcess
    conclusion: Literal["未发现问题", "发现审核问题", "审核未完整完成"]
    total_rules: int
    passed_count: int = 0
    failed_count: int = 0
    not_applicable_count: int = 0
    undetermined_count: int = 0
    error_count: int = 0
    issue_count: int = 0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0


class ReviewResult(BaseModel):
    task_id: str
    snapshot_id: str
    status: TaskStatus
    summary: ReviewSummary
    issues: list[Issue]
    rule_results: list[RuleExecutionResult]
    batch_logs: list[BatchLog]
    failed_rule_ids: list[str] = Field(default_factory=list)
