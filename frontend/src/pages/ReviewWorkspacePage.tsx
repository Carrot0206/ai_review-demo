import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Collapse,
  Empty,
  Popconfirm,
  Progress,
  Segmented,
  Skeleton,
  Tag,
  Upload,
  message,
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  InboxOutlined,
  ReloadOutlined,
  RocketOutlined,
} from '@ant-design/icons'
import {
  cancelRuleEngineReview,
  createRuleEngineReview,
  deleteReviewUpload,
  getReviewUploadExtracted,
  getRuleEngineHealth,
  getRuleEngineReview,
  getRuleEngineReviewResult,
  listReviewUploads,
  retryRuleEngineReview,
  subscribeRuleEngineEvents,
  uploadReviewFile,
} from '../api'
import ReviewIssueCard from '../components/review/ReviewIssueCard'
import { PROCESS_LABELS, PROCESS_OPTIONS } from '../components/rule-library/config'
import type {
  ExtractedMaterial,
  ReviewIssue,
  ReviewTaskStatus,
  ReviewUpload,
  RiskLevel,
  RuleEngineReviewResult,
  RuleLibraryProcess,
} from '../types'
import './reviewWorkspace.css'


const { Dragger } = Upload

const TEMPLATE_SECTIONS: Record<RuleLibraryProcess, string[]> = {
  pre_registration: [
    '产品基本信息',
    '业务分类信息',
    '交易结构',
    '底层资产及交易对手',
    '托管信息',
    '风险控制信息',
    '房地产项目信息',
    '异地推介信息',
    '关联交易信息',
  ],
  pre_report: ['产品基本信息', '关联交易事项'],
  initial: [
    '产品基本信息',
    '业务分类信息',
    '产品特征',
    '互联网贷款信息',
    '信托费用信息',
    '初始信托规模',
    '共同受托人信息',
    '初始委托人及其财产信息',
    '初始受益权信息',
  ],
  termination: ['产品基本信息', '期限信息', '财务信息', '其他信息'],
}

const TERMINAL_STATUSES = new Set<ReviewTaskStatus>([
  'done',
  'partial_failed',
  'failed',
  'cancelled',
  'interrupted',
])

const STATUS_LABELS: Record<ReviewTaskStatus, string> = {
  queued: '等待执行',
  running: '正在审核',
  done: '审核完成',
  partial_failed: '部分批次失败',
  failed: '审核失败',
  cancelled: '已取消',
  interrupted: '服务中断',
}

interface TemplateField {
  label: string
  value: string
  location: string
}

interface TemplateRecord {
  index: number
  fields: TemplateField[]
}

interface TemplateSection {
  name: string
  fields: TemplateField[]
  records: TemplateRecord[]
}

interface ReviewSession {
  taskId: string | null
  status: ReviewTaskStatus | 'idle'
  ruleCount: number
  completedCount: number
  progressPercent: number
  result: RuleEngineReviewResult | null
  error: string
  events: string[]
}

function emptySession(): ReviewSession {
  return {
    taskId: null,
    status: 'idle',
    ruleCount: 0,
    completedCount: 0,
    progressPercent: 0,
    result: null,
    error: '',
    events: [],
  }
}

function initialSessions(): Record<RuleLibraryProcess, ReviewSession> {
  return {
    pre_registration: emptySession(),
    pre_report: emptySession(),
    initial: emptySession(),
    termination: emptySession(),
  }
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function isTemplateUpload(upload: ReviewUpload) {
  return upload.material_type === '申报模板' || upload.original_name.includes('模板')
}

function normalizeLocation(location: string, sections: string[]) {
  const raw = (location || '').trim()
  for (const section of sections) {
    if (raw === section || raw.startsWith(`${section}.`) || raw.startsWith(`${section}[`)) return raw
    const markerIndex = raw.indexOf(`.${section}`)
    if (markerIndex >= 0) return raw.slice(markerIndex + 1)
  }
  return raw
}

function buildTemplateSections(material: ExtractedMaterial | null, process: RuleLibraryProcess) {
  const sectionNames = TEMPLATE_SECTIONS[process]
  const sections: TemplateSection[] = sectionNames.map((name) => ({ name, fields: [], records: [] }))
  if (!material) return sections
  const sectionMap = new Map(sections.map((section) => [section.name, section]))
  const recordMaps = new Map<string, Map<number, TemplateRecord>>()

  for (const segment of material.segments) {
    const normalized = normalizeLocation(segment.location, sectionNames)
    const sectionName = sectionNames.find(
      (name) => normalized === name || normalized.startsWith(`${name}.`) || normalized.startsWith(`${name}[`),
    )
    if (!sectionName) continue
    const section = sectionMap.get(sectionName)
    if (!section) continue
    const remainder = normalized.slice(sectionName.length)
    const arrayMatch = remainder.match(/^\[(\d+)\]\.(.+)$/)
    if (arrayMatch) {
      const recordIndex = Number(arrayMatch[1]) + 1
      let recordMap = recordMaps.get(sectionName)
      if (!recordMap) {
        recordMap = new Map()
        recordMaps.set(sectionName, recordMap)
      }
      let record = recordMap.get(recordIndex)
      if (!record) {
        record = { index: recordIndex, fields: [] }
        recordMap.set(recordIndex, record)
        section.records.push(record)
      }
      record.fields.push({ label: arrayMatch[2], value: segment.text, location: segment.location })
      continue
    }
    const fieldMatch = remainder.match(/^\.(.+)$/)
    if (fieldMatch && !fieldMatch[1].includes('.')) {
      section.fields.push({ label: fieldMatch[1], value: segment.text, location: segment.location })
    }
  }

  for (const section of sections) {
    section.records.sort((left, right) => left.index - right.index)
    if (section.records.length === 1 && section.fields.length === 0) {
      section.fields = section.records[0].fields
      section.records = []
    }
  }
  return sections
}

function stripIndexes(value: string) {
  return value.replace(/\[\d+\]/g, '')
}

function canonicalLocation(value: string) {
  return stripIndexes(value)
    .replace(/^(?:第?[一二三四五六七八九十百]+[章节部分、.．]|\d+[、.．])\s*/, '')
    .replace(/\s+/g, '')
}

function locationsMatch(left: string, right: string) {
  const normalizedLeft = canonicalLocation(left.trim())
  const normalizedRight = canonicalLocation(right.trim())
  return normalizedLeft === normalizedRight || normalizedLeft.endsWith(normalizedRight) || normalizedRight.endsWith(normalizedLeft)
}

function issuesForField(field: TemplateField, issues: ReviewIssue[], material: ExtractedMaterial | null) {
  return issues.filter((issue) => issue.issue_location.some((location) => {
    if (location.material_name && material && location.material_name !== material.material_name) return false
    return locationsMatch(field.location, location.location)
  }))
}

function topRisk(issues: ReviewIssue[]): RiskLevel | null {
  const weights: Record<RiskLevel, number> = { 高风险: 3, 中风险: 2, 低风险: 1 }
  return issues.reduce<RiskLevel | null>((current, issue) => {
    if (!current || weights[issue.risk_level] > weights[current]) return issue.risk_level
    return current
  }, null)
}

function riskClass(risk: RiskLevel | null) {
  if (risk === '高风险') return 'high'
  if (risk === '中风险') return 'mid'
  if (risk === '低风险') return 'low'
  return ''
}

function statusColor(status: ReviewSession['status']) {
  if (status === 'done') return 'success'
  if (status === 'running' || status === 'queued') return 'processing'
  if (status === 'partial_failed' || status === 'interrupted') return 'warning'
  if (status === 'failed' || status === 'cancelled') return 'error'
  return 'default'
}

export default function ReviewWorkspacePage() {
  const [process, setProcess] = useState<RuleLibraryProcess>('pre_registration')
  const [uploads, setUploads] = useState<ReviewUpload[]>([])
  const [uploadsLoading, setUploadsLoading] = useState(false)
  const [templateMaterial, setTemplateMaterial] = useState<ExtractedMaterial | null>(null)
  const [templateLoading, setTemplateLoading] = useState(false)
  const [sessions, setSessions] = useState(initialSessions)
  const [riskFilters, setRiskFilters] = useState<Set<RiskLevel>>(new Set(['高风险', '中风险', '低风险']))
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null)
  const [selectedIssueNonce, setSelectedIssueNonce] = useState(0)
  const [openDimensions, setOpenDimensions] = useState<string[]>([])
  const streamClosers = useRef(new Map<string, () => void>())
  const syncTimers = useRef(new Map<string, number>())
  const fieldRefs = useRef(new Map<string, HTMLDivElement>())
  const issueRefs = useRef(new Map<string, HTMLElement>())
  const session = sessions[process]
  const running = session.status === 'queued' || session.status === 'running'
  const canRetry = session.status === 'partial_failed' || session.status === 'failed' || session.status === 'interrupted'

  const updateSession = useCallback((targetProcess: RuleLibraryProcess, patch: Partial<ReviewSession>) => {
    setSessions((current) => ({
      ...current,
      [targetProcess]: { ...current[targetProcess], ...patch },
    }))
  }, [])

  const appendEvent = useCallback((targetProcess: RuleLibraryProcess, text: string) => {
    setSessions((current) => ({
      ...current,
      [targetProcess]: {
        ...current[targetProcess],
        events: [...current[targetProcess].events.slice(-7), text],
      },
    }))
  }, [])

  const refreshUploads = useCallback(async (targetProcess: RuleLibraryProcess) => {
    setUploadsLoading(true)
    try {
      setUploads(await listReviewUploads(targetProcess))
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '材料列表加载失败')
    } finally {
      setUploadsLoading(false)
    }
  }, [])

  useEffect(() => {
    setSelectedIssueId(null)
    setSelectedIssueNonce(0)
    setOpenDimensions([])
    refreshUploads(process)
  }, [process, refreshUploads])

  const templateUpload = useMemo(
    () => [...uploads].filter(isTemplateUpload).sort((left, right) => right.uploaded_at - left.uploaded_at)[0],
    [uploads],
  )

  useEffect(() => {
    let cancelled = false
    if (!templateUpload) {
      setTemplateMaterial(null)
      return
    }
    setTemplateLoading(true)
    getReviewUploadExtracted(templateUpload.file_id)
      .then((material) => {
        if (!cancelled) setTemplateMaterial(material)
      })
      .catch(() => {
        if (!cancelled) setTemplateMaterial(null)
      })
      .finally(() => {
        if (!cancelled) setTemplateLoading(false)
      })
    return () => { cancelled = true }
  }, [templateUpload])

  const templateSections = useMemo(
    () => buildTemplateSections(templateMaterial, process),
    [process, templateMaterial],
  )

  const visibleIssues = useMemo(
    () => (session.result?.issues || []).filter((issue) => riskFilters.has(issue.risk_level)),
    [riskFilters, session.result],
  )

  useEffect(() => {
    if (!selectedIssueId) return
    const issue = session.result?.issues.find((item) => item.issue_id === selectedIssueId)
    const location = issue?.issue_location.find((item) => !item.material_name || item.material_name === templateMaterial?.material_name)
    if (!location) return
    const field = [...fieldRefs.current.entries()].find(([fieldLocation]) => locationsMatch(fieldLocation, location.location))
    field?.[1].scrollIntoView({ behavior: 'smooth', block: 'center' })
    window.requestAnimationFrame(() => {
      issueRefs.current.get(selectedIssueId)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }, [selectedIssueId, selectedIssueNonce, session.result, templateMaterial])

  const syncReview = useCallback(async (taskId: string, targetProcess: RuleLibraryProcess) => {
    try {
      const status = await getRuleEngineReview(taskId)
      updateSession(targetProcess, {
        status: status.status,
        ruleCount: status.rule_count,
        completedCount: status.completed_rule_count,
        progressPercent: status.progress_percent,
        error: status.error,
      })
      if (TERMINAL_STATUSES.has(status.status)) {
        streamClosers.current.get(taskId)?.()
        streamClosers.current.delete(taskId)
        const result = await getRuleEngineReviewResult(taskId)
        updateSession(targetProcess, { result })
      }
    } catch (error: any) {
      updateSession(targetProcess, { error: error?.response?.data?.detail || error?.message || '任务状态读取失败' })
    }
  }, [updateSession])

  const scheduleSync = useCallback((taskId: string, targetProcess: RuleLibraryProcess, immediate = false) => {
    const existing = syncTimers.current.get(taskId)
    if (existing) window.clearTimeout(existing)
    const timer = window.setTimeout(() => {
      syncTimers.current.delete(taskId)
      syncReview(taskId, targetProcess)
    }, immediate ? 0 : 180)
    syncTimers.current.set(taskId, timer)
  }, [syncReview])

  const attachStream = useCallback((taskId: string, targetProcess: RuleLibraryProcess) => {
    streamClosers.current.get(taskId)?.()
    const close = subscribeRuleEngineEvents(
      taskId,
      (eventType, payload) => {
        if (eventType === 'task_started') appendEvent(targetProcess, '规则快照已加载，开始执行审核')
        if (eventType === 'script_completed') appendEvent(targetProcess, `脚本审核完成，AI兜底 ${Array.isArray(payload.fallback_rule_ids) ? payload.fallback_rule_ids.length : 0} 条`)
        if (eventType === 'batch_update') appendEvent(targetProcess, 'AI审核批次已更新')
        if (eventType === 'task_finished') appendEvent(targetProcess, '全部规则执行完成，正在汇总结果')
        if (eventType === 'task_failed') appendEvent(targetProcess, '审核任务执行失败')
        if (eventType === 'task_cancelled') appendEvent(targetProcess, '审核任务已取消')
        scheduleSync(taskId, targetProcess, eventType.startsWith('task_') && eventType !== 'task_started')
      },
      () => scheduleSync(taskId, targetProcess),
    )
    streamClosers.current.set(taskId, close)
  }, [appendEvent, scheduleSync])

  useEffect(() => () => {
    streamClosers.current.forEach((close) => close())
    syncTimers.current.forEach((timer) => window.clearTimeout(timer))
  }, [])

  async function handleUpload(file: File) {
    try {
      const uploaded = await uploadReviewFile(process, file)
      await refreshUploads(process)
      if (uploaded.parse_status === '已解析') {
        message.success(`${file.name} 上传并解析成功`)
      } else {
        message.error(`${file.name} 上传成功，但解析失败：${uploaded.parse_error || '未知原因'}`)
      }
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || '上传失败'
      if (error?.response?.status === 409) message.warning(detail)
      else message.error(`上传失败：${detail}`)
    }
    return false
  }

  async function handleDeleteUpload(fileId: string) {
    try {
      await deleteReviewUpload(fileId)
      await refreshUploads(process)
      message.success('材料已删除')
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '材料删除失败')
    }
  }

  async function handleStartReview() {
    if (uploads.length === 0) {
      message.warning('请先上传申请材料')
      return
    }
    const unavailableUploads = uploads.filter((upload) => upload.parse_status !== '已解析')
    if (unavailableUploads.length > 0) {
      const first = unavailableUploads[0]
      message.error(`${first.original_name} 尚未解析成功：${first.parse_error || first.parse_status || '未知原因'}`)
      return
    }
    const targetProcess = process
    try {
      const health = await getRuleEngineHealth()
      if (!health.ai_configured) {
        message.error('规则引擎未配置DEEPSEEK_API_KEY，AI规则无法执行，请配置后重启规则引擎')
        return
      }
      updateSession(targetProcess, { ...emptySession(), status: 'queued', events: ['正在加载规则引擎材料'] })
      const created = await createRuleEngineReview(targetProcess, uploads.map((upload) => upload.file_id))
      updateSession(targetProcess, {
        taskId: created.task_id,
        status: created.status,
        ruleCount: created.rule_count,
        events: [`审核任务已创建，共加载 ${created.rule_count} 条启用规则`],
      })
      attachStream(created.task_id, targetProcess)
      scheduleSync(created.task_id, targetProcess, true)
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || '审核任务创建失败'
      updateSession(targetProcess, { status: 'failed', error: String(detail) })
      message.error(`启动审核失败：${typeof detail === 'string' ? detail : JSON.stringify(detail)}`)
    }
  }

  async function handleCancelReview() {
    if (!session.taskId) return
    try {
      await cancelRuleEngineReview(session.taskId)
      scheduleSync(session.taskId, process, true)
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '取消审核失败')
    }
  }

  async function handleRetryReview() {
    if (!session.taskId) return
    try {
      await retryRuleEngineReview(session.taskId)
      updateSession(process, { status: 'queued', error: '', events: [...session.events, '正在重试失败批次'] })
      attachStream(session.taskId, process)
      scheduleSync(session.taskId, process, true)
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '重试失败')
    }
  }

  function toggleRisk(risk: RiskLevel) {
    setRiskFilters((current) => {
      const next = new Set(current)
      if (next.has(risk)) next.delete(risk)
      else next.add(risk)
      return next
    })
  }

  function selectIssue(issue: ReviewIssue) {
    setOpenDimensions((current) => current.includes(issue.review_dimension)
      ? current
      : [...current, issue.review_dimension])
    setSelectedIssueId(issue.issue_id)
    setSelectedIssueNonce((current) => current + 1)
  }

  function renderField(field: TemplateField) {
    const issues = issuesForField(field, session.result?.issues || [], templateMaterial)
    const risk = topRisk(issues)
    const linkedIssue = issues.find((issue) => riskFilters.has(issue.risk_level))
    return (
      <div
        className="review-template-field"
        key={field.location}
        ref={(node) => {
          if (node) fieldRefs.current.set(field.location, node)
          else fieldRefs.current.delete(field.location)
        }}
      >
        <div className="review-template-label">{field.label}：</div>
        <button
          type="button"
          className={`review-template-value ${riskClass(risk)}${linkedIssue ? ' has-issue' : ''}`}
          disabled={!linkedIssue}
          onClick={() => linkedIssue && selectIssue(linkedIssue)}
          title={linkedIssue ? '点击查看关联问题' : undefined}
        >
          <span>{field.value || '（空）'}</span>
          {risk && <span className="review-template-warning">!</span>}
        </button>
      </div>
    )
  }

  function renderFields(fields: TemplateField[]) {
    const rows: TemplateField[][] = []
    for (let index = 0; index < fields.length; index += 2) rows.push(fields.slice(index, index + 2))
    return rows.map((row, index) => (
      <div className="review-template-row" key={index}>
        {row.map(renderField)}
        {row.length === 1 && <div className="review-template-field empty" />}
      </div>
    ))
  }

  function sectionFieldCount(section: TemplateSection) {
    return section.fields.length + section.records.reduce((count, record) => count + record.fields.length, 0)
  }

  const groupedIssues = useMemo(() => {
    const groups = new Map<string, ReviewIssue[]>()
    for (const issue of visibleIssues) {
      const items = groups.get(issue.review_dimension) || []
      items.push(issue)
      groups.set(issue.review_dimension, items)
    }
    return [...groups.entries()]
  }, [visibleIssues])

  useEffect(() => {
    if (!session.result) {
      setOpenDimensions([])
      return
    }
    setOpenDimensions([...new Set(session.result.issues.map((issue) => issue.review_dimension))])
  }, [session.result])

  const failedBatchErrors = useMemo(() => {
    const errors = new Set(
      (session.result?.batch_logs || [])
        .filter((batch) => batch.status === 'failed' && batch.error)
        .map((batch) => batch.error),
    )
    return [...errors]
  }, [session.result])

  return (
    <div className="review-workspace-page">
      <header className="review-workspace-header">
        <div className="review-workspace-brand"><FileSearchOutlined /></div>
        <div>
          <h1>信托产品登记审核</h1>
          <span>上传申请材料，由规则引擎加载当前流程全部启用规则并完成审核</span>
        </div>
        <div className="review-workspace-header-spacer" />
        {session.status !== 'idle' && (
          <Tag color={statusColor(session.status)}>{STATUS_LABELS[session.status]}</Tag>
        )}
      </header>

      <main className="review-workspace-main">
        <section className="review-process-band" aria-label="登记流程选择">
          <span>登记流程</span>
          <Segmented
            block
            value={process}
            options={PROCESS_OPTIONS}
            onChange={(value) => setProcess(value as RuleLibraryProcess)}
          />
          <small>审核任务创建时自动固化对应流程规则快照</small>
        </section>

        <div className="review-workspace-grid">
          <div className="review-workspace-left">
            <section className="review-panel review-actions-panel">
              <div className="review-panel-header">
                <h2>材料准备</h2>
                <Tag color={uploads.length ? 'success' : 'default'}>材料 {uploads.length}</Tag>
              </div>
              <div className="review-action-grid">
                <div className="review-upload-block">
                  <div className="review-block-title">上传材料</div>
                  <Dragger
                    multiple
                    disabled={running}
                    beforeUpload={handleUpload}
                    showUploadList={false}
                    accept=".json,.pdf,.docx,.txt,.xlsx,.xlsm"
                  >
                    <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                    <p className="review-upload-title">点击或拖拽上传申请材料</p>
                    <p className="review-muted">支持 JSON、PDF、DOCX、TXT、XLSX 和 XLSM</p>
                  </Dragger>

                  {uploadsLoading ? (
                    <Skeleton active paragraph={{ rows: 2 }} title={false} />
                  ) : uploads.length > 0 ? (
                    <div className="review-upload-list">
                      {uploads.map((upload) => (
                        <div className="review-upload-item" key={upload.file_id}>
                          <FileTextOutlined className="review-upload-icon" />
                          <div className="review-upload-meta">
                            <strong title={upload.original_name}>{upload.original_name}</strong>
                            <div>
                              {upload.material_type && <Tag color="geekblue">{upload.material_type}</Tag>}
                              {upload.parse_status && <Tag color={upload.parse_status === '已解析' ? 'success' : 'warning'}>{upload.parse_status}</Tag>}
                              <span>{formatSize(upload.size_bytes)}</span>
                            </div>
                          </div>
                          <Popconfirm
                            title="删除该材料？"
                            okText="删除"
                            cancelText="取消"
                            onConfirm={() => handleDeleteUpload(upload.file_id)}
                          >
                            <Button type="text" danger icon={<DeleteOutlined />} disabled={running} aria-label="删除材料" />
                          </Popconfirm>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>

                <div className="review-start-block">
                  <div className="review-block-title">开始审核</div>
                  <div className="review-start-summary">
                    <span>当前流程</span>
                    <strong>{PROCESS_LABELS[process]}</strong>
                    <span>申报模板</span>
                    <strong>{templateUpload?.original_name || '尚未上传'}</strong>
                  </div>

                  {running ? (
                    <>
                      <Progress percent={Math.round(session.progressPercent)} status="active" />
                      <Button danger block size="large" icon={<CloseCircleOutlined />} onClick={handleCancelReview}>
                        取消审核
                      </Button>
                    </>
                  ) : (
                    <Button type="primary" block size="large" icon={<RocketOutlined />} onClick={handleStartReview}>
                      开始审核
                    </Button>
                  )}

                  {session.ruleCount > 0 && (
                    <div className="review-task-count">
                      已完成 {session.completedCount} / {session.ruleCount} 条规则
                    </div>
                  )}
                  {session.events.length > 0 && (
                    <div className="review-event-log" aria-live="polite">
                      {session.events.slice(-3).map((event, index) => <div key={`${event}-${index}`}>{event}</div>)}
                    </div>
                  )}
                  {session.error && <Alert type="error" showIcon message={session.error} />}
                </div>
              </div>
            </section>

            <section className="review-panel review-template-panel">
              <div className="review-panel-header">
                <h2>申报模板内容</h2>
                <div>
                  {templateMaterial && <Tag color="geekblue">{templateMaterial.material_name}</Tag>}
                  {session.result && <Tag color="error">字段问题 {session.result.issues.length}</Tag>}
                </div>
              </div>
              <div className="review-template-body">
                {!templateUpload ? (
                  <Empty description="暂无申报模板，请先上传申请材料" />
                ) : templateLoading ? (
                  <Skeleton active paragraph={{ rows: 8 }} />
                ) : !templateMaterial ? (
                  <Empty description="申报模板尚未解析完成或解析失败" />
                ) : (
                  <Collapse
                    className="review-template-collapse"
                    defaultActiveKey={[templateSections[0]?.name].filter(Boolean)}
                    items={templateSections.map((section) => {
                      const fields = [...section.fields, ...section.records.flatMap((record) => record.fields)]
                      const issueCount = fields.filter((field) => issuesForField(field, session.result?.issues || [], templateMaterial).length > 0).length
                      return {
                        key: section.name,
                        label: (
                          <span className="review-template-section-label">
                            <strong>{section.name}</strong>
                            <span>{sectionFieldCount(section)} 个字段</span>
                            {issueCount > 0 && <em>标注 {issueCount} 处异常</em>}
                          </span>
                        ),
                        children: (
                          <div className="review-template-table">
                            {section.fields.length > 0 && renderFields(section.fields)}
                            {section.records.map((record) => (
                              <div className="review-template-record" key={record.index}>
                                <div className="review-template-record-title">{section.name}[{record.index}]</div>
                                {renderFields(record.fields)}
                              </div>
                            ))}
                            {sectionFieldCount(section) === 0 && <div className="review-template-empty">暂无数据</div>}
                          </div>
                        ),
                      }
                    })}
                  />
                )}
              </div>
            </section>
          </div>

          <aside className="review-panel review-result-panel">
            <div className="review-panel-header review-result-heading">
              <h2>审核结果</h2>
              {session.status !== 'idle' && <Tag color={statusColor(session.status)}>{STATUS_LABELS[session.status]}</Tag>}
            </div>

            {session.result ? (
              <>
                {session.result.summary.conclusion === '审核未完整完成' && (
                  <Alert
                    banner
                    type="warning"
                    message="审核未完整完成"
                    description={failedBatchErrors.length
                      ? `AI批次错误：${failedBatchErrors.join('；')}`
                      : '部分规则证据不足或执行失败，请查看统计并按需重试失败批次。'}
                    action={canRetry ? <Button size="small" icon={<ReloadOutlined />} onClick={handleRetryReview}>重试失败批次</Button> : undefined}
                  />
                )}
                <div className="review-conclusion">
                  <CheckCircleOutlined className={session.result.summary.issue_count ? 'has-issues' : ''} />
                  <div>
                    <strong>{session.result.summary.conclusion}</strong>
                    <span>共执行 {session.result.summary.total_rules} 条规则</span>
                  </div>
                </div>
                <div className="review-stats">
                  <div className="total"><strong>{session.result.summary.issue_count}</strong><span>问题总数</span></div>
                  <div className="high"><strong>{session.result.summary.high_risk_count}</strong><span>高风险</span></div>
                  <div className="mid"><strong>{session.result.summary.medium_risk_count}</strong><span>中风险</span></div>
                  <div className="low"><strong>{session.result.summary.low_risk_count}</strong><span>低风险</span></div>
                  <div><strong>{session.result.summary.undetermined_count + session.result.summary.error_count}</strong><span>未完整判断</span></div>
                </div>
                <div className="review-result-toolbar">
                  <span>风险筛选</span>
                  {(['高风险', '中风险', '低风险'] as RiskLevel[]).map((risk) => (
                    <Tag.CheckableTag key={risk} checked={riskFilters.has(risk)} onChange={() => toggleRisk(risk)}>
                      {risk}
                    </Tag.CheckableTag>
                  ))}
                </div>
                <div className="review-result-body">
                  {groupedIssues.length === 0 ? (
                    <Empty description={session.result.issues.length ? '当前筛选条件下暂无问题' : '未发现审核问题'} />
                  ) : (
                    <Collapse
                      className="review-dimension-collapse"
                      activeKey={openDimensions}
                      onChange={(keys) => setOpenDimensions((Array.isArray(keys) ? keys : [keys]).map(String))}
                      items={groupedIssues.map(([dimension, issues]) => ({
                        key: dimension,
                        label: <span className="review-dimension-label"><strong>{dimension}</strong><Tag>{issues.length} 条</Tag></span>,
                        children: issues.map((issue) => (
                          <ReviewIssueCard
                            key={issue.issue_id}
                            ref={(node) => {
                              if (node) issueRefs.current.set(issue.issue_id, node)
                              else issueRefs.current.delete(issue.issue_id)
                            }}
                            issue={issue}
                            selected={selectedIssueId === issue.issue_id}
                            forceOpen={selectedIssueId === issue.issue_id}
                            openSignal={selectedIssueId === issue.issue_id ? selectedIssueNonce : 0}
                            onSelect={(selected) => setSelectedIssueId(selected.issue_id)}
                          />
                        )),
                      }))}
                    />
                  )}
                </div>
              </>
            ) : running ? (
              <div className="review-running-state">
                <FileSearchOutlined />
                <h3>规则引擎正在审核</h3>
                <Progress percent={Math.round(session.progressPercent)} status="active" />
                <p>脚本规则与AI规则并行执行，结果会持续更新。</p>
                <Skeleton active paragraph={{ rows: 8 }} />
              </div>
            ) : session.status === 'failed' ? (
              <div className="review-result-empty">
                <CloseCircleOutlined />
                <h3>审核未能完成</h3>
                <p>{session.error || '请检查服务配置后重新发起审核。'}</p>
                {session.taskId && <Button icon={<ReloadOutlined />} onClick={handleRetryReview}>重试失败任务</Button>}
              </div>
            ) : (
              <div className="review-result-empty">
                <FileSearchOutlined />
                <h3>等待开始审核</h3>
                <p>上传材料并开始审核后，问题卡片将在这里展示。</p>
              </div>
            )}
          </aside>
        </div>
      </main>
    </div>
  )
}
