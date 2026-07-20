import axios from 'axios'
import type {
  RuleLibraryImportPreview,
  RuleLibraryProcess,
  RuleLibraryResponse,
  RuleLibraryRule,
  RuleLibraryRuleInput,
  ExtractedMaterial,
  ReviewTaskStatus,
  ReviewUpload,
  RuleEngineReviewResult,
  RuleEngineReviewStatus,
} from './types'


const http = axios.create({ baseURL: '/api', timeout: 60_000 })

export async function getRuleLibraryRules(process: RuleLibraryProcess): Promise<RuleLibraryResponse> {
  const { data } = await http.get('/rule-library/rules', { params: { process } })
  return data
}

export async function createRuleLibraryRule(payload: RuleLibraryRuleInput): Promise<RuleLibraryRule> {
  const { data } = await http.post('/rule-library/rules', payload)
  return data
}

export async function updateRuleLibraryRule(ruleId: string, payload: RuleLibraryRuleInput): Promise<RuleLibraryRule> {
  const { data } = await http.put(`/rule-library/rules/${ruleId}`, payload)
  return data
}

export async function copyRuleLibraryRule(ruleId: string): Promise<RuleLibraryRule> {
  const { data } = await http.post(`/rule-library/rules/${ruleId}/copy`)
  return data
}

export async function setRuleLibraryRuleEnabled(ruleId: string, enabled: boolean): Promise<RuleLibraryRule> {
  const { data } = await http.patch(`/rule-library/rules/${ruleId}/enabled`, { enabled })
  return data
}

export async function deleteRuleLibraryRule(ruleId: string) {
  const { data } = await http.delete(`/rule-library/rules/${ruleId}`)
  return data
}

export async function deleteRuleLibraryRules(ruleIds: string[]) {
  const { data } = await http.post('/rule-library/rules/batch-delete', { rule_ids: ruleIds })
  return data as { deleted_count: number; requested_count: number }
}

export async function deleteRuleLibraryRulesByProcess(process: RuleLibraryProcess) {
  const { data } = await http.delete('/rule-library/rules/by-process', { params: { process } })
  return data as { process: RuleLibraryProcess; deleted_count: number }
}

export async function previewRuleLibraryImport(process: RuleLibraryProcess, file: File): Promise<RuleLibraryImportPreview> {
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
  const { data } = await http.get('/rule-library/template', { params: { process }, responseType: 'blob' })
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = `${process}_rule_library_template.xlsx`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export async function listReviewUploads(process: RuleLibraryProcess): Promise<ReviewUpload[]> {
  const { data } = await http.get('/rule-engine/materials', { params: { process } })
  return data
}

export async function uploadReviewFile(
  process: RuleLibraryProcess,
  file: File,
): Promise<ReviewUpload> {
  const form = new FormData()
  form.append('file', file)
  form.append('process', process)
  const { data } = await http.post('/rule-engine/materials', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function deleteReviewUpload(fileId: string) {
  const { data } = await http.delete(`/rule-engine/materials/${fileId}`)
  return data
}

export async function getReviewUploadExtracted(fileId: string): Promise<ExtractedMaterial> {
  const { data } = await http.get(`/rule-engine/materials/${fileId}/extracted`)
  return data
}

export async function createRuleEngineReview(
  process: RuleLibraryProcess,
  fileIds: string[],
): Promise<{ task_id: string; snapshot_id: string; status: ReviewTaskStatus; rule_count: number }> {
  const { data } = await http.post('/rule-engine/reviews', { process, file_ids: fileIds })
  return data
}

export async function getRuleEngineHealth(): Promise<{
  status: string
  service: string
  ai_configured: boolean
  ai_model: string
}> {
  const { data } = await http.get('/rule-engine/health')
  return data
}

export async function getRuleEngineReview(taskId: string): Promise<RuleEngineReviewStatus> {
  const { data } = await http.get(`/rule-engine/reviews/${taskId}`)
  return data
}

export async function getRuleEngineReviewResult(taskId: string): Promise<RuleEngineReviewResult> {
  const { data } = await http.get(`/rule-engine/reviews/${taskId}/result`)
  return data
}

export async function cancelRuleEngineReview(taskId: string) {
  const { data } = await http.post(`/rule-engine/reviews/${taskId}/cancel`)
  return data as { task_id: string; status: ReviewTaskStatus }
}

export async function retryRuleEngineReview(taskId: string) {
  const { data } = await http.post(`/rule-engine/reviews/${taskId}/retry-failed`)
  return data as { task_id: string; status: ReviewTaskStatus; retry_rule_ids: string[] }
}

const REVIEW_EVENT_TYPES = [
  'task_started',
  'script_completed',
  'batch_update',
  'task_finished',
  'task_failed',
  'task_cancelled',
  'task_retry',
] as const

export function subscribeRuleEngineEvents(
  taskId: string,
  onEvent: (eventType: string, payload: Record<string, unknown>) => void,
  onConnectionError?: () => void,
) {
  const source = new EventSource(`/api/rule-engine/reviews/${taskId}/events`)
  for (const eventType of REVIEW_EVENT_TYPES) {
    source.addEventListener(eventType, (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data)
        onEvent(eventType, payload)
      } catch {
        onEvent(eventType, {})
      }
    })
  }
  source.onerror = () => onConnectionError?.()
  return () => source.close()
}
