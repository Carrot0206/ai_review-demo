export type RiskLevel = '高风险' | '中风险' | '低风险'

export type RuleLibraryProcess =
  | 'pre_registration'
  | 'pre_report'
  | 'initial'
  | 'termination'

export type RuleLibraryMethod = 'script' | 'ai'
export type RuleLibraryObject = '文件' | '材料' | '表' | '字段' | '跨材料'
export type RuleLibraryDimension =
  | '文件格式标准化'
  | '法定要素完整性'
  | '文本语义合规'
  | '跨文件数据一致性'
  | '非标资产穿透'
  | '报送时效合规'

export interface RuleLibraryRuleInput {
  rule_id: string
  rule_name: string
  process: RuleLibraryProcess
  review_method: RuleLibraryMethod
  applicable_materials: string[]
  rule_object: RuleLibraryObject
  table_name: string
  field_path: string
  review_dimension: RuleLibraryDimension
  trigger_condition: string
  rule_text: string
  basis_text: string
  risk_level: RiskLevel
  version: string
  enabled: boolean
  remarks: string
  operator: string
  script_params: Record<string, unknown>
  special_prompt: string
}

export interface RuleLibraryRule extends RuleLibraryRuleInput {
  source_file: string
  source_sheet: string
  source_row: number
  created_at: number
  updated_at: number
  visual_rule: string
}

export interface RuleLibraryResponse {
  process: RuleLibraryProcess
  total: number
  script_count: number
  ai_count: number
  enabled_count: number
  rules: RuleLibraryRule[]
}

export interface RuleLibraryImportIssue {
  sheet: string
  row: number
  rule_id: string
  message: string
}

export interface RuleLibraryImportPreview {
  filename: string
  process: RuleLibraryProcess
  total_rules: number
  script_count: number
  ai_count: number
  valid: boolean
  errors: RuleLibraryImportIssue[]
  preview: RuleLibraryRule[]
}

export type ReviewTaskStatus =
  | 'queued'
  | 'running'
  | 'done'
  | 'partial_failed'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export type RuleExecutionStatus =
  | 'passed'
  | 'failed'
  | 'not_applicable'
  | 'undetermined'
  | 'error'

export type RuleExecutionMethod = 'script' | 'ai' | 'ai_fallback'

export interface ReviewUpload {
  file_id: string
  original_name: string
  size_bytes: number
  material_type?: string | null
  process?: RuleLibraryProcess | null
  uploaded_at: number
  parse_status?: string
  parse_error?: string | null
  parser_profile?: string
  template_version?: string
  request_type?: string
  mapping_version?: string
  parse_warnings?: string[]
}

export interface MaterialSegment {
  location: string
  text: string
  raw_location?: string
  raw_text?: string
}

export interface ExtractedMaterial {
  material_name: string
  material_type: string
  file_kind: 'json' | 'pdf' | 'docx' | 'txt' | 'excel' | 'unknown'
  size_bytes?: number | null
  segments: MaterialSegment[]
  parser_profile?: string
  template_version?: string
  request_type?: string
  mapping_version?: string
  parse_warnings?: string[]
}

export interface RuleEvidence {
  material_name: string
  location: string
  value: string
}

export interface RuleBasis {
  basis_type: string
  basis_file: string
  rule_text: string
}

export interface ReviewIssue {
  issue_id: string
  rule_id: string
  review_dimension: string
  issue_summary: string
  risk_level: RiskLevel
  rule_basis: RuleBasis
  issue_location: RuleEvidence[]
  suggestion: string
  execution_method: RuleExecutionMethod
  rule_ids: string[]
  rule_dimensions: string[]
  rule_bases: RuleBasis[]
}

export interface RuleExecutionResult {
  rule_id: string
  status: RuleExecutionStatus
  execution_method: RuleExecutionMethod
  summary: string
  suggestion: string
  evidence: RuleEvidence[]
  error: string
  batch_id: string
  duration_seconds: number
}

export interface RuleEngineBatchLog {
  batch_id: string
  execution_method: 'ai' | 'ai_fallback'
  review_dimension: string
  rule_ids: string[]
  status: 'running' | 'success' | 'failed' | 'cancelled'
  duration_seconds: number
  input_tokens: number
  output_tokens: number
  materials_used: string[]
  error: string
  attempts: number
}

export interface RuleEngineSummary {
  process: RuleLibraryProcess
  conclusion: '未发现问题' | '发现审核问题' | '审核未完整完成'
  total_rules: number
  passed_count: number
  failed_count: number
  not_applicable_count: number
  undetermined_count: number
  error_count: number
  issue_count: number
  high_risk_count: number
  medium_risk_count: number
  low_risk_count: number
}

export interface RuleEngineReviewResult {
  task_id: string
  snapshot_id: string
  status: ReviewTaskStatus
  summary: RuleEngineSummary
  issues: ReviewIssue[]
  rule_results: RuleExecutionResult[]
  batch_logs: RuleEngineBatchLog[]
  failed_rule_ids: string[]
}

export interface RuleEngineReviewStatus {
  task_id: string
  process: RuleLibraryProcess
  snapshot_id: string
  status: ReviewTaskStatus
  rule_count: number
  completed_rule_count: number
  progress_percent: number
  status_counts: Record<RuleExecutionStatus, number>
  created_at: number
  started_at: number | null
  finished_at: number | null
  error: string
}
