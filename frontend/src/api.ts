import axios from 'axios'
import type {
  BatchLog,
  ExtractedMaterial,
  Issue,
  JobInfo,
  ProcessType,
  RiskLevel,
  RuleListResponse,
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

export async function deleteUserRule(rule_id: string) {
  const { data } = await http.delete(`/user-rules/${rule_id}`)
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
  user_rule_ids?: string[] | null
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

/** SSE 订阅。返回 close 函数。 */
export function subscribeReviewStream(
  job_id: string,
  onMsg: (msg: string) => void,
  onDone: () => void,
  onFailed: (err: string) => void,
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
  es.onerror = () => {
    // EventSource 会自动重连；保留默认行为
  }
  return () => es.close()
}
