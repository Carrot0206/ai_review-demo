// 与后端 schemas 对齐
export type ProcessType =
  | 'pre_report'
  | 'initial'
  | 'pre_registration'
  | 'pre_registration_reapply'
  | 'pre_registration_supplement'
  | 'termination'
  | 'change_general'
  | 'correction_general'
export type RiskLevel = '高风险' | '中风险' | '低风险'

export interface Rule {
  rule_id: string
  rule_name: string
  rule_text: string
  rule_category: string
  rule_type: string
  business_scenario: string
  review_dimension: string
  check_type: string
  applicable_processes: string[]
  applicable_materials: string[]
  basis_file: string
  risk_level: RiskLevel
  severity_type?: 'issue' | 'risk_hint'
  issue_type?: string
}

export interface HumanReviewItem {
  rule_id: string
  rule_name: string
  rule_text: string
  reason: string
}

export interface RuleListResponse {
  process: ProcessType
  total: number
  ai_count: number
  human_count: number
  rules: Rule[]
  user_rules: UserRule[]
  rule_sets?: RuleSetMeta[]
}

export interface RuleSetMeta {
  rule_set_id: string
  process: ProcessType
  filename: string
  created_at: number
  active: boolean
  total_rules: number
  script_count: number
  ai_count: number
  unsupported_count: number
  error_count: number
  warning_count: number
  scope_count?: number
  report?: {
    errors?: { sheet?: string; row?: number; rule_id?: string; message: string }[]
    warnings?: { sheet?: string; row?: number; rule_id?: string; message: string }[]
  }
}

export interface UserRule {
  rule_id: string
  process: ProcessType
  applicable_materials: string[]
  rule_text: string
  risk_level: RiskLevel
  review_dimension?: string
  check_type?: string
  table_name?: string
  field_name?: string
  trigger_condition?: string
  created_at: number
  enabled: boolean
}

export interface UploadMeta {
  file_id: string
  original_name: string
  stored_name?: string
  ext?: string
  size_bytes: number
  material_type?: string | null
  process?: ProcessType | null
  uploaded_at: number
  segment_count?: number
  segments_count?: number
  size_human?: string
  parse_status?: string
  parse_error?: string | null
}

export interface ExtractedSegment {
  location: string
  text: string
}

export interface ExtractedMaterial {
  material_name: string
  material_type: string
  file_kind: 'json' | 'pdf' | 'docx' | 'txt' | 'excel' | 'unknown'
  segments: ExtractedSegment[]
}

export interface RuleBasis {
  basis_type: '内置规则' | '用户新增规则'
  basis_file: string
  rule_text: string
}

export interface IssueLocation {
  material_name: string
  location: string
  value: string
}

export interface Issue {
  issue_id: string
  rule_id: string
  review_dimension?: string
  issue_summary: string
  risk_level: RiskLevel
  rule_basis: RuleBasis
  issue_location: IssueLocation[]
  suggestion: string
  severity_type?: 'issue' | 'risk_hint'
  issue_type?: string
  rule_ids: string[]
  rule_dimensions?: string[]
  rule_bases: RuleBasis[]
  alt_summaries: string[]
  alt_suggestions: string[]
}

export interface BatchLog {
  batch_id: string
  review_dimension: string
  rule_count: number
  status: 'success' | 'failed'
  issues_found: number
  duration_seconds: number
  input_tokens: number
  output_tokens: number
  error?: string | null
  materials_used?: string[]
  slice_enabled?: boolean
  slice_summary?: string
  original_segment_count?: number
  sliced_segment_count?: number
  slice_fallback?: boolean
  slice_confidence?: string
}

export interface ReviewSummary {
  registration_type: string
  total_issues: number
  high_risk_count: number
  medium_risk_count: number
  low_risk_count: number
  risk_hint_count?: number
}

export interface ReviewResult {
  summary: ReviewSummary
  issues: Issue[]
  deduped_summary?: ReviewSummary | null
  deduped_issues?: Issue[]
  human_review_items: HumanReviewItem[]
  batch_logs: BatchLog[]
  scope_decisions?: ScopeDecision[]
}

export interface ScopeDecision {
  scope_id: string
  table_name: string
  status: 'required' | 'not_required' | 'prohibited' | 'unknown' | 'conflict'
  reason: string
  source: 'script' | 'ai' | 'script+ai'
  table_present: boolean
  evidence: IssueLocation[]
}

export interface JobInfo {
  job_id: string
  process: ProcessType
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
  started_at: number
  finished_at?: number | null
  error?: string | null
  result?: ReviewResult | null
  progress_log: { ts: number; msg: string }[]
}

export interface SampleFile {
  name: string
  size_bytes: number
  material_type?: string | null
}

export interface SampleListResponse {
  pre_report: SampleFile[]
  initial: SampleFile[]
  pre_registration: SampleFile[]
  pre_registration_reapply: SampleFile[]
  pre_registration_supplement: SampleFile[]
  termination: SampleFile[]
  change_general: SampleFile[]
  correction_general: SampleFile[]
}

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
