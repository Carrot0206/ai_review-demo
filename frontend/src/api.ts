import axios from 'axios'
import type {
  BatchLog,
  ExtractedMaterial,
  Issue,
  JobInfo,
  ProcessType,
  RiskLevel,
  RuleLibraryImportPreview,
  RuleLibraryProcess,
  RuleLibraryResponse,
  RuleLibraryRule,
  RuleLibraryRuleInput,
  RuleListResponse,
  RuleSetMeta,
  SampleListResponse,
  UploadMeta,
  UserRule,
} from './types'

const http = axios.create({
  baseURL: '/api',
  timeout: 60_000,
})

export async function health() {
  const { data } = await http.get('/health')
  return data
}

export async function getRules(process: ProcessType): Promise<RuleListResponse> {
  const { data } = await http.get('/rules', { params: { process } })
  return data
}

export async function getUserRules(process: ProcessType): Promise<UserRule[]> {
  const { data } = await http.get('/user-rules', { params: { process } })
  return data
}

export async function createUserRule(payload: {
  process: ProcessType
  applicable_materials: string[]
  rule_text: string
  risk_level: RiskLevel
  review_dimension?: string
  check_type?: string
  table_name?: string
  field_name?: string
  trigger_condition?: string
}): Promise<UserRule> {
  const { data } = await http.post('/user-rules', payload)
  return data
}

export async function importUserRules(
  process: ProcessType,
  file: File,
): Promise<{ filename: string; process: ProcessType; imported_count: number; rules: UserRule[] }> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/user-rules/import', form, {
    params: { process },
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function listRuleSets(process: ProcessType): Promise<RuleSetMeta[]> {
  const { data } = await http.get('/rule-sets', { params: { process } })
  return data.rule_sets || []
}

export async function importRuleSet(
  process: ProcessType,
  file: File,
): Promise<RuleSetMeta> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/rule-sets/import', form, {
    params: { process },
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function activateRuleSet(rule_set_id: string): Promise<RuleSetMeta> {
  const { data } = await http.post(`/rule-sets/${rule_set_id}/activate`)
  return data
}

export async function deleteRuleSet(rule_set_id: string): Promise<{
  deleted: boolean
  rule_set_id: string
  filename: string
  process: ProcessType
  was_active: boolean
}> {
  const { data } = await http.delete(`/rule-sets/${rule_set_id}`)
  return data
}

export async function deleteUserRule(rule_id: string) {
  const { data } = await http.delete(`/user-rules/${rule_id}`)
  return data
}

export async function deleteUserRulesBatch(rule_ids: string[]): Promise<{ deleted_count: number; requested_count: number }> {
  const { data } = await http.post('/user-rules/batch-delete', { rule_ids })
  return data
}

export async function updateUserRule(
  rule_id: string,
  payload: {
    applicable_materials?: string[]
    rule_text?: string
    risk_level?: RiskLevel
    review_dimension?: string
    check_type?: string
    table_name?: string
    field_name?: string
    trigger_condition?: string
  },
): Promise<UserRule> {
  const { data } = await http.put(`/user-rules/${rule_id}`, payload)
  return data
}

export async function listUploads(process?: ProcessType): Promise<UploadMeta[]> {
  const { data } = await http.get('/upload', {
    params: process ? { process } : undefined,
  })
  return data
}

export async function uploadFile(
  file: File,
  opts?: { material_type?: string; process?: ProcessType },
): Promise<UploadMeta> {
  const form = new FormData()
  form.append('file', file)
  if (opts?.material_type) form.append('material_type', opts.material_type)
  if (opts?.process) form.append('process', opts.process)
  const { data } = await http.post('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function deleteUpload(file_id: string) {
  const { data } = await http.delete(`/upload/${file_id}`)
  return data
}

export async function getUploadExtracted(file_id: string): Promise<ExtractedMaterial> {
  const { data } = await http.get(`/upload/${file_id}/extracted`)
  return data
}

export async function listSamples(): Promise<SampleListResponse> {
  const { data } = await http.get('/samples')
  return data
}

export async function loadSamples(process: ProcessType): Promise<{ process: ProcessType; files: UploadMeta[]; skipped?: { name: string; reason: string }[] }> {
  const { data } = await http.post('/samples/load', { process })
  return data
}

export async function startReview(payload: {
  process: ProcessType
  file_ids: string[]
  rule_set_id?: string | null
  include_builtin_rules?: boolean
  max_concurrency?: number
  material_slice_enabled?: boolean
}): Promise<{ job_id: string; status: string }> {
  const { data } = await http.post('/review', payload)
  return data
}

export async function getReview(job_id: string): Promise<JobInfo> {
  const { data } = await http.get(`/review/${job_id}`)
  return data
}

export async function cancelReview(job_id: string): Promise<{ job_id: string; status: string; cancelled: boolean }> {
  const { data } = await http.post(`/review/${job_id}/cancel`)
  return data
}

export async function getRuleLibraryRules(
  process: RuleLibraryProcess,
): Promise<RuleLibraryResponse> {
  const { data } = await http.get('/rule-library/rules', { params: { process } })
  return data
}

export async function createRuleLibraryRule(
  payload: RuleLibraryRuleInput,
): Promise<RuleLibraryRule> {
  const { data } = await http.post('/rule-library/rules', payload)
  return data
}

export async function updateRuleLibraryRule(
  ruleId: string,
  payload: RuleLibraryRuleInput,
): Promise<RuleLibraryRule> {
  const { data } = await http.put(`/rule-library/rules/${ruleId}`, payload)
  return data
}

export async function copyRuleLibraryRule(ruleId: string): Promise<RuleLibraryRule> {
  const { data } = await http.post(`/rule-library/rules/${ruleId}/copy`)
  return data
}

export async function setRuleLibraryRuleEnabled(
  ruleId: string,
  enabled: boolean,
): Promise<RuleLibraryRule> {
  const { data } = await http.patch(`/rule-library/rules/${ruleId}/enabled`, { enabled })
  return data
}

export async function deleteRuleLibraryRule(ruleId: string) {
  const { data } = await http.delete(`/rule-library/rules/${ruleId}`)
  return data
}

export async function deleteRuleLibraryRules(ruleIds: string[]) {
  const { data } = await http.post('/rule-library/rules/batch-delete', {
    rule_ids: ruleIds,
  })
  return data as { deleted_count: number; requested_count: number }
}

export async function deleteRuleLibraryRulesByProcess(process: RuleLibraryProcess) {
  const { data } = await http.delete('/rule-library/rules/by-process', {
    params: { process },
  })
  return data as { process: RuleLibraryProcess; deleted_count: number }
}

export async function previewRuleLibraryImport(
  process: RuleLibraryProcess,
  file: File,
): Promise<RuleLibraryImportPreview> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/rule-library/import/preview', form, {
    params: { process },
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function commitRuleLibraryImport(
  process: RuleLibraryProcess,
  file: File,
): Promise<{ imported_count: number; script_count: number; ai_count: number }> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/rule-library/import/commit', form, {
    params: { process },
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function downloadRuleLibraryTemplate(process: RuleLibraryProcess) {
  const { data } = await http.get('/rule-library/template', {
    params: { process },
    responseType: 'blob',
  })
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = `${process}_rule_library_template.xlsx`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

/** SSE 订阅。返回 close 函数。 */
export function subscribeReviewStream(
  job_id: string,
  onMsg: (msg: string) => void,
  onDone: () => void,
  onFailed: (err: string) => void,
  onCancelled: () => void,
  onBatchDone?: (payload: { batch: BatchLog; issues: Issue[] }) => void,
): () => void {
  const url = `/api/review/${job_id}/stream`
  const es = new EventSource(url)
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data?.msg) onMsg(String(data.msg))
    } catch {
      /* keep-alive */
    }
  }
  es.addEventListener('batch_done', (e) => {
    if (!onBatchDone) return
    try {
      const data = JSON.parse((e as MessageEvent).data)
      onBatchDone(data as { batch: BatchLog; issues: Issue[] })
    } catch {
      /* ignore */
    }
  })
  es.addEventListener('done', () => {
    onDone()
    es.close()
  })
  es.addEventListener('failed', (e) => {
    try {
      const data = JSON.parse((e as MessageEvent).data)
      onFailed(String(data?.error || 'failed'))
    } catch {
      onFailed('failed')
    }
    es.close()
  })
  es.addEventListener('cancelled', () => {
    onCancelled()
    es.close()
  })
  es.onerror = () => {
    // EventSource 会自动重连；保留默认行为
  }
  return () => es.close()
}
