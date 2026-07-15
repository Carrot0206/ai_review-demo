import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Button,
  Collapse,
  Empty,
  Popconfirm,
  Switch,
  Tag,
  Tooltip,
  Upload,
  message,
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  InboxOutlined,
  ImportOutlined,
  RocketOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import {
  activateRuleSet,
  cancelReview,
  deleteRuleSet,
  deleteUpload,
  getReview,
  getUploadExtracted,
  getRules,
  importRuleSet,
  listRuleSets,
  listUploads,
  loadSamples,
  startReview,
  subscribeReviewStream,
  uploadFile,
} from '../api'
import { useStore } from '../store'
import type { ExtractedMaterial, Issue, ProcessType, RiskLevel, UploadMeta } from '../types'

const { Dragger } = Upload

const TEMPLATE_SECTIONS: Record<ProcessType, string[]> = {
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
  pre_registration_reapply: [
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
  pre_registration_supplement: [
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
  pre_report: ['产品基本信息', '关联交易事项'],
  termination: ['产品基本信息', '期限信息', '财务信息', '其他信息'],
  change_general: [
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
  correction_general: [
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
}

const PROCESS_LABELS: Record<ProcessType, string> = {
  pre_registration: '预登记',
  pre_registration_reapply: '重新申请预登记',
  pre_registration_supplement: '补充预登记',
  pre_report: '事前报告',
  initial: '初始登记',
  termination: '终止登记',
  change_general: '变更登记（一般情形）',
  correction_general: '更正登记（一般情形）',
}

const RISK_WEIGHT: Record<RiskLevel, number> = {
  高风险: 3,
  中风险: 2,
  低风险: 1,
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

interface TemplateSectionData {
  name: string
  fields: TemplateField[]
  records: TemplateRecord[]
}

function fmtSize(b: number) {
  if (b < 1024) return b + ' B'
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB'
  return (b / 1024 / 1024).toFixed(1) + ' MB'
}

function isBaselineUpload(u: UploadMeta) {
  const haystack = `${u.original_name || ''} ${u.material_type || ''}`.toLowerCase()
  return (
    u.material_type === '原预登记申报模板JSON' ||
    u.material_type === '原预登记系统记录' ||
    haystack.includes('原预登记') ||
    haystack.includes('baseline')
  )
}

function isPreviousRegistrationUpload(u: UploadMeta) {
  return u.material_type === '上一次登记申报模板'
}

function isChangeCurrentMaterial(u: UploadMeta) {
  return !isPreviousRegistrationUpload(u)
}

function isFollowupRegistrationProcess(process: ProcessType) {
  return process === 'change_general' || process === 'correction_general'
}

function isTemplateUpload(u: UploadMeta) {
  if (isBaselineUpload(u)) return false
  if (isPreviousRegistrationUpload(u)) return false
  return u.material_type === '申报模板' || u.original_name.includes('模板')
}

function normalizeLocationToSection(location: string, sections: string[]) {
  const raw = (location || '').trim()
  if (!raw) return ''
  for (const section of sections) {
    if (raw === section || raw.startsWith(`${section}.`) || raw.startsWith(`${section}[`)) {
      return raw
    }
    const marker = `.${section}`
    const idx = raw.indexOf(marker)
    if (idx >= 0) return raw.slice(idx + 1)
  }
  return raw
}

function shiftArrayIndexes(location: string, delta: number) {
  return location.replace(/\[(\d+)\]/g, (_, n: string) => {
    const next = Number(n) + delta
    return next >= 0 ? `[${next}]` : `[${n}]`
  })
}

function locationVariants(location: string, sections: string[]) {
  const normalized = normalizeLocationToSection(location, sections)
  return new Set([
    (location || '').trim(),
    normalized,
    shiftArrayIndexes(normalized, 1),
    shiftArrayIndexes(normalized, -1),
  ].filter(Boolean))
}

function fieldMatchesIssueLocation(fieldLocation: string, issueLocation: string, sections: string[]) {
  const fieldKeys = locationVariants(fieldLocation, sections)
  const issueKeys = locationVariants(issueLocation, sections)
  for (const key of fieldKeys) {
    if (issueKeys.has(key)) return true
  }
  return false
}

function buildTemplateSections(material: ExtractedMaterial | null, process: ProcessType) {
  const sectionNames = TEMPLATE_SECTIONS[process]
  const sections: TemplateSectionData[] = sectionNames.map((name) => ({
    name,
    fields: [],
    records: [],
  }))
  if (!material) return sections

  const byName = new Map(sections.map((section) => [section.name, section]))
  const recordsBySection = new Map<string, Map<number, TemplateRecord>>()
  for (const segment of material.segments || []) {
    const normalized = normalizeLocationToSection(segment.location, sectionNames)
    const sectionName = sectionNames.find(
      (name) =>
        normalized === name ||
        normalized.startsWith(`${name}.`) ||
        normalized.startsWith(`${name}[`),
    )
    if (!sectionName) continue
    const section = byName.get(sectionName)
    if (!section) continue
    const rest = normalized.slice(sectionName.length)
    const arrayMatch = rest.match(/^\[(\d+)\]\.(.+)$/)
    if (arrayMatch) {
      const rowIndex = arrayMatch[1]
      const fieldName = arrayMatch[2]
      const recordIndex = Number(rowIndex) + 1
      let sectionRecords = recordsBySection.get(sectionName)
      if (!sectionRecords) {
        sectionRecords = new Map()
        recordsBySection.set(sectionName, sectionRecords)
      }
      let record = sectionRecords.get(recordIndex)
      if (!record) {
        record = { index: recordIndex, fields: [] }
        sectionRecords.set(recordIndex, record)
        section.records.push(record)
      }
      record.fields.push({
        label: fieldName,
        value: segment.text,
        location: segment.location,
      })
      continue
    }

    const fieldMatch = rest.match(/^\.(.+)$/)
    if (!fieldMatch) continue
    const fieldName = fieldMatch[1]
    if (fieldName.includes('.')) continue
    section.fields.push({
      label: fieldName,
      value: segment.text,
      location: segment.location,
    })
  }

  for (const section of sections) {
    section.records.sort((a, b) => a.index - b.index)
    if (section.records.length === 1 && section.fields.length === 0) {
      section.fields = section.records[0].fields
      section.records = []
    }
  }

  return sections
}

function getIssuesForField(
  location: string,
  issues: Issue[],
  material: ExtractedMaterial | null,
  sections: string[],
) {
  if (!material || !location) return []
  return issues.filter((issue) =>
    (issue.issue_location || []).some((loc) => {
      if (loc.material_name && loc.material_name !== material.material_name) return false
      return fieldMatchesIssueLocation(location, loc.location, sections)
    }),
  )
}

function topRisk(issues: Issue[]) {
  return issues.reduce<RiskLevel | null>((risk, issue) => {
    if (!risk) return issue.risk_level
    return RISK_WEIGHT[issue.risk_level] > RISK_WEIGHT[risk] ? issue.risk_level : risk
  }, null)
}

function riskClass(level: RiskLevel | null) {
  if (level === '高风险') return 'high'
  if (level === '中风险') return 'mid'
  if (level === '低风险') return 'low'
  return ''
}

function allSectionFields(section: TemplateSectionData) {
  return [
    ...section.fields,
    ...section.records.flatMap((record) => record.fields),
  ]
}

function countSectionIssues(
  section: TemplateSectionData,
  issues: Issue[],
  material: ExtractedMaterial | null,
  process: ProcessType,
) {
  if (!material || issues.length === 0) return 0
  const sectionNames = TEMPLATE_SECTIONS[process]
  let markedFields = 0
  for (const field of allSectionFields(section)) {
    const fieldMatches = getIssuesForField(field.location, issues, material, sectionNames)
    if (fieldMatches.length > 0) markedFields += 1
  }
  return markedFields
}

function guessChangeGeneralMaterialType(fileName: string) {
  if (fileName.includes('申请书')) return '申请书'
  if (fileName.includes('证明') || fileName.includes('变更事实')) {
    return '证明发生变更事实的文件'
  }
  if (fileName.includes('模板')) return '申报模板'
  return '其他附件'
}

function guessCorrectionGeneralMaterialType(fileName: string) {
  if (fileName.includes('申请书')) return '申请书'
  if (fileName.includes('证明') || fileName.includes('更正事实')) {
    return '证明发生需要更正事实的文件'
  }
  if (fileName.includes('模板')) return '申报模板'
  return '其他附件'
}

function guessFollowupRegistrationMaterialType(process: ProcessType, fileName: string) {
  if (process === 'correction_general') return guessCorrectionGeneralMaterialType(fileName)
  return guessChangeGeneralMaterialType(fileName)
}

export default function LeftPanel() {
  const process = useStore((s) => s.process)
  const rules = useStore((s) => s.rules)
  const ruleSets = useStore((s) => s.ruleSets)
  const uploads = useStore((s) => s.uploads)
  const setUploads = useStore((s) => s.setUploads)
  const setRuleSets = useStore((s) => s.setRuleSets)
  const setRules = useStore((s) => s.setRules)

  const setJobId = useStore((s) => s.setJobId)
  const setJobStatus = useStore((s) => s.setJobStatus)
  const setStage = useStore((s) => s.setStage)
  const appendProgress = useStore((s) => s.appendProgress)
  const resetProgress = useStore((s) => s.resetProgress)
  const setResult = useStore((s) => s.setResult)
  const appendBatchIssues = useStore((s) => s.appendBatchIssues)
  const setBatchTotal = useStore((s) => s.setBatchTotal)
  const resetBatchProgress = useStore((s) => s.resetBatchProgress)
  const jobStatus = useStore((s) => s.jobStatusByProcess[s.process])
  const result = useStore((s) => s.resultByProcess[s.process])
  const showDeduped = useStore((s) => s.showDedupedByProcess[s.process])
  const materialSliceEnabled = useStore((s) => s.materialSliceByProcess[s.process])
  const setMaterialSlice = useStore((s) => s.setMaterialSlice)
  const builtinRulesEnabled = useStore((s) => s.builtinRulesEnabledByProcess[s.process])
  const setBuiltinRulesEnabled = useStore((s) => s.setBuiltinRulesEnabled)
  const filterRisks = useStore((s) => s.filterRisks)
  const setSelectedIssue = useStore((s) => s.setSelectedIssue)
  const selectedFieldLocation = useStore((s) => s.selectedFieldLocationByProcess[s.process])
  const jobId = useStore((s) => s.jobIdByProcess[s.process])

  const [templateMaterial, setTemplateMaterial] = useState<ExtractedMaterial | null>(null)
  const [templateLoading, setTemplateLoading] = useState(false)
  const fieldRefs = useRef(new Map<string, HTMLDivElement>())
  const reviewStreamCloseRef = useRef<(() => void) | null>(null)

  const builtinRules = useMemo(() => rules?.rules || [], [rules])
  const activeRuleSet = useMemo(() => ruleSets.find((item) => item.active), [ruleSets])
  const processLabel = PROCESS_LABELS[process]
  const isFollowupProcess = isFollowupRegistrationProcess(process)
  const followupShortLabel = process === 'correction_general' ? '更正' : '变更'
  const followupProcessLabel =
    process === 'correction_general' ? '更正登记（一般情形）' : '变更登记（一般情形）'

  // 当前流程下的上传文件（演示版：全部都展示）
  const currentUploads = uploads
  const hasReapplyBaseline = useMemo(
    () => currentUploads.some(isBaselineUpload),
    [currentUploads],
  )
  const templateUpload = useMemo(() => {
    return [...currentUploads]
      .filter(isTemplateUpload)
      .sort((a, b) => (b.uploaded_at || 0) - (a.uploaded_at || 0))[0]
  }, [currentUploads])

  useEffect(() => {
    let canceled = false
    if (!templateUpload) {
      setTemplateMaterial(null)
      setTemplateLoading(false)
      return
    }
    setTemplateLoading(true)
    getUploadExtracted(templateUpload.file_id)
      .then((data) => {
        if (!canceled) setTemplateMaterial(data)
      })
      .catch(() => {
        if (!canceled) setTemplateMaterial(null)
      })
      .finally(() => {
        if (!canceled) setTemplateLoading(false)
      })
    return () => {
      canceled = true
    }
  }, [templateUpload])

  const displayIssues = useMemo(
    () =>
      showDeduped && result?.deduped_issues?.length
        ? result.deduped_issues
        : result?.issues || [],
    [result, showDeduped],
  )
  const fieldIssues = useMemo(
    () => displayIssues.filter((issue) => issue.severity_type !== 'risk_hint'),
    [displayIssues],
  )
  const visibleIssueIds = useMemo(
    () => new Set(fieldIssues.filter((issue) => filterRisks.has(issue.risk_level)).map((issue) => issue.issue_id)),
    [fieldIssues, filterRisks],
  )
  const templateSections = useMemo(
    () => buildTemplateSections(templateMaterial, process),
    [process, templateMaterial],
  )

  useEffect(() => {
    if (!selectedFieldLocation) return
    window.requestAnimationFrame(() => {
      const node = fieldRefs.current.get(selectedFieldLocation)
      node?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }, [selectedFieldLocation])

  function handleSelectFieldIssue(issues: Issue[]) {
    if (issues.length === 0) return
    const visible = issues.find((issue) => visibleIssueIds.has(issue.issue_id))
    if (!visible) {
      return
    }
    setSelectedIssue(visible.issue_id, process)
  }

  async function refreshUploads() {
    const list = await listUploads(process)
    setUploads(list)
  }
  async function refreshRules() {
    const r = await getRules(process)
    setRules(r)
    const versions = await listRuleSets(process)
    setRuleSets(versions)
  }

  async function handleUpload(file: File, materialType?: string) {
    try {
      await uploadFile(file, { process, material_type: materialType })
      message.success(`${file.name} 上传成功`)
      await refreshUploads()
    } catch (e: any) {
      const status = e?.response?.status
      const detail = e?.response?.data?.detail || e?.message
      if (status === 409) {
        message.warning(detail || '同名文件已存在，未重复添加')
      } else {
        message.error('上传失败：' + detail)
      }
    }
    return false // 阻止 antd 自带上传
  }

  function handleFollowupRegistrationCurrentUpload(file: File) {
    return handleUpload(file, guessFollowupRegistrationMaterialType(process, file.name))
  }

  async function handleLoadSamples() {
    try {
      const res = await loadSamples(process)
      if (res.files.length > 0) {
        message.success(`已载入 ${res.files.length} 份样例材料`)
      }
      if (res.skipped && res.skipped.length > 0) {
        message.warning(
          `${res.skipped.length} 份样例已存在被跳过：${res.skipped
            .map((s) => s.name)
            .join('、')}`,
        )
      }
      if (res.files.length === 0 && (!res.skipped || res.skipped.length === 0)) {
        message.info('未找到可载入的样例文件')
      }
      await refreshUploads()
    } catch (e: any) {
      message.error('载入样例失败：' + (e?.response?.data?.detail || e?.message))
    }
  }

  async function handleDelete(fileId: string) {
    await deleteUpload(fileId)
    await refreshUploads()
  }

  async function handleImportRules(file: File) {
    try {
      const res = await importRuleSet(process, file)
      await activateRuleSet(res.rule_set_id)
      message.success(
        `已导入并启用 ${res.filename}：脚本 ${res.script_count} 条，AI ${res.ai_count} 条，范围 ${res.scope_count || 0} 条`,
      )
      await refreshRules()
    } catch (e: any) {
      message.error('规则表导入失败：' + (e?.response?.data?.detail || e?.message))
    }
    return false
  }

  async function handleActivateRuleSet(ruleSetId: string) {
    try {
      await activateRuleSet(ruleSetId)
      message.success('已启用规则版本')
      await refreshRules()
    } catch (e: any) {
      message.error('启用失败：' + (e?.response?.data?.detail || e?.message))
    }
  }

  async function handleDeleteRuleSet(ruleSetId: string) {
    try {
      const res = await deleteRuleSet(ruleSetId)
      message.success(`已删除规则版本：${res.filename}`)
      await refreshRules()
    } catch (e: any) {
      message.error('删除规则版本失败：' + (e?.response?.data?.detail || e?.message))
    }
  }

  async function handleStart() {
    if (currentUploads.length === 0) {
      message.warning('请先上传材料或一键载入样例')
      return
    }
    const availableRuleCount =
      (builtinRulesEnabled ? builtinRules.length : 0) +
      (activeRuleSet ? activeRuleSet.total_rules : 0)
    if (availableRuleCount === 0) {
      message.warning('当前流程没有可用审核规则，请启用内置规则或上传规则版本')
      return
    }
    // 锁定本次审核所属流程,避免审核过程中用户切流程时回调写到错误流程
    const reviewProcess = process
    resetProgress(reviewProcess)
    resetBatchProgress(reviewProcess)
    setResult(null, reviewProcess)
    setJobId(null, reviewProcess)
    setStage('parse', reviewProcess)
    setJobStatus('pending', reviewProcess)
    reviewStreamCloseRef.current?.()
    reviewStreamCloseRef.current = null
    try {
      const { job_id } = await startReview({
        process: reviewProcess,
        file_ids: currentUploads.map((u) => u.file_id),
        rule_set_id: activeRuleSet?.rule_set_id || null,
        include_builtin_rules: builtinRulesEnabled,
        max_concurrency: 48,
        material_slice_enabled: materialSliceEnabled,
      })
      setJobId(job_id, reviewProcess)
      setJobStatus('running', reviewProcess)
      setStage('batch', reviewProcess)

      reviewStreamCloseRef.current = subscribeReviewStream(
        job_id,
        (msg) => {
          appendProgress(msg, reviewProcess)
          // 从 "分组完成：共 N 批" 抓总批次数
          const m = msg.match(/分组完成[：:]\s*共\s*(\d+)\s*批/)
          if (m) setBatchTotal(parseInt(m[1], 10), reviewProcess)
          if (msg.includes('分组完成')) setStage('batch', reviewProcess)
          if (msg.includes('全部批次完成') || msg.includes('合并') || msg.includes('去重')) {
            setStage('merge', reviewProcess)
          }
        },
        async () => {
          reviewStreamCloseRef.current = null
          setStage('done', reviewProcess)
          setJobStatus('done', reviewProcess)
          // 拉取最终结果（覆盖累积区为合并后的最终版）
          const job = await getReview(job_id)
          setResult(job.result || null, reviewProcess)
          setJobId(null, reviewProcess)
        },
        (err) => {
          reviewStreamCloseRef.current = null
          setStage('failed', reviewProcess)
          setJobStatus('failed', reviewProcess)
          setJobId(null, reviewProcess)
          message.error('审核失败：' + err)
        },
        () => {
          reviewStreamCloseRef.current = null
          setStage('cancelled', reviewProcess)
          setJobStatus('cancelled', reviewProcess)
          setJobId(null, reviewProcess)
          setResult(null, reviewProcess)
          appendProgress('审核已取消', reviewProcess)
          message.info('已取消审核')
        },
        (payload) => {
          // O6：批次完成事件 → 累积到 store，触发 RightPanel 重渲染
          appendBatchIssues(payload, reviewProcess)
        },
      )
    } catch (e: any) {
      setStage('failed', reviewProcess)
      setJobStatus('failed', reviewProcess)
      message.error('启动审核失败：' + (e?.response?.data?.detail || e?.message))
    }
  }

  const running = jobStatus === 'pending' || jobStatus === 'running'

  async function handleCancelReview() {
    if (!jobId || !running) return
    const reviewProcess = process
    reviewStreamCloseRef.current?.()
    reviewStreamCloseRef.current = null
    setStage('cancelled', reviewProcess)
    setJobStatus('cancelled', reviewProcess)
    setResult(null, reviewProcess)
    appendProgress('正在取消审核…', reviewProcess)
    try {
      await cancelReview(jobId)
      appendProgress('审核已取消', reviewProcess)
      setJobId(null, reviewProcess)
      message.info('已取消审核')
    } catch (e: any) {
      setStage('failed', reviewProcess)
      setJobStatus('failed', reviewProcess)
      message.error('取消审核失败：' + (e?.response?.data?.detail || e?.message))
    }
  }

  function renderIssueBadge(issues: Issue[]) {
    const risk = topRisk(issues)
    if (!risk) return null
    return (
      <span className={`template-issue-badge ${riskClass(risk)}`}>
        !
      </span>
    )
  }

  function renderFieldValue(value: string, location: string) {
    const issues = getIssuesForField(
      location,
      fieldIssues,
      templateMaterial,
      TEMPLATE_SECTIONS[process],
    )
    const risk = topRisk(issues)
    const clickable = issues.length > 0
    return (
      <button
        type="button"
        className={`template-field-value ${riskClass(risk)} ${clickable ? 'has-issue' : ''}`}
        onClick={() => handleSelectFieldIssue(issues)}
        disabled={!clickable}
        title={clickable ? '点击查看关联问题' : undefined}
      >
        <span>{value || '（空）'}</span>
        {renderIssueBadge(issues)}
      </button>
    )
  }

  function renderTemplateSection(section: TemplateSectionData) {
    if (section.fields.length === 0 && section.records.length === 0) {
      return <div className="template-empty-row">暂无数据</div>
    }

    function renderFields(fields: TemplateField[]) {
      const rows: TemplateField[][] = []
      for (let i = 0; i < fields.length; i += 2) {
        rows.push(fields.slice(i, i + 2))
      }
      return rows.map((row, idx) => (
        <div className="template-field-row" key={idx}>
          {row.map((field) => (
            <div
              className="template-field-cell"
              key={field.location}
              ref={(node) => {
                if (node) fieldRefs.current.set(field.location, node)
                else fieldRefs.current.delete(field.location)
              }}
            >
              <div className="template-field-label">{field.label}：</div>
              <div className="template-field-content">
                {renderFieldValue(field.value, field.location)}
              </div>
            </div>
          ))}
          {row.length === 1 && <div className="template-field-cell empty" />}
        </div>
      ))
    }

    return (
      <div className="template-field-table">
        {section.fields.length > 0 && renderFields(section.fields)}
        {section.records.map((record, idx) => (
          <div className="template-record-block" key={record.index}>
            <div className="template-record-title">
              {section.name}[{record.index}]：
            </div>
            {renderFields(record.fields)}
            {idx < section.records.length - 1 && <div className="template-record-divider" />}
          </div>
        ))}
      </div>
    )
  }

  return (
    <>
      <div className="panel action-panel">
        <div className="panel-header">
          <h3>审核工作台 · {processLabel}</h3>
          <div className="right">
            <Tag color="processing">内置规则 {builtinRules.length}</Tag>
            <Tag color={activeRuleSet ? 'purple' : 'default'}>
              规则版本 {ruleSets.length}
            </Tag>
            <Tag color={currentUploads.length > 0 ? 'success' : 'default'}>
              材料 {currentUploads.length}
            </Tag>
          </div>
        </div>
        <div className="panel-body action-grid">
          <section className="action-block rules-block">
            <div className="action-block-title">规则</div>
            <Collapse
              size="small"
              ghost
              items={[
                {
                  key: 'builtin',
                  label: (
                    <span style={{ fontSize: 13, fontWeight: 600 }}>
                      内置规则（{builtinRules.length}）
                    </span>
                  ),
                  children: (
                    <div className="compact-scroll">
                      <div className="review-option-row compact-rule-option">
                        <div>
                          <div className="review-option-title">启用内置规则</div>
                          <div className="muted">关闭后本次审核只使用已启用的上传规则版本</div>
                        </div>
                        <Switch
                          checked={builtinRulesEnabled}
                          onChange={(checked) => setBuiltinRulesEnabled(checked, process)}
                          disabled={running}
                        />
                      </div>
                      {builtinRules.length === 0 && (
                        <div className="muted" style={{ padding: '4px 0' }}>
                          暂未加载到内置规则
                        </div>
                      )}
                      {builtinRules.slice(0, 40).map((r) => (
                        <div key={r.rule_id} className="rule-row">
                          <span className="rid">{r.rule_id}</span>
                          <span className="txt">
                            <Tooltip title={r.rule_text}>
                              <span>
                                <strong>{r.rule_name}</strong>
                                <span className="muted" style={{ marginLeft: 6 }}>
                                  · {r.review_dimension}
                                </span>
                              </span>
                            </Tooltip>
                          </span>
                        </div>
                      ))}
                      {builtinRules.length > 40 && (
                        <div className="muted" style={{ textAlign: 'center', padding: 6 }}>
                          … 还有 {builtinRules.length - 40} 条
                        </div>
                      )}
                    </div>
                  ),
                },
                {
                  key: 'user',
                  label: (
                    <span style={{ fontSize: 13, fontWeight: 600 }}>
                      上传规则版本（{ruleSets.length}）
                    </span>
                  ),
                  children: (
                    <>
                      <div className="rule-actions">
                        <Upload
                          beforeUpload={handleImportRules}
                          showUploadList={false}
                          accept=".xlsx,.xlsm"
                        >
                          <Button
                            type="dashed"
                            size="small"
                            icon={<ImportOutlined />}
                            block
                          >
                            上传规则 Excel
                          </Button>
                        </Upload>
                      </div>
                      <div className="compact-scroll">
                        {ruleSets.length === 0 ? (
                          <div className="muted" style={{ padding: '4px 0' }}>
                            暂无上传规则版本
                          </div>
                        ) : (
                          ruleSets.map((r) => (
                            <div key={r.rule_set_id} className="rule-row">
                              <span className="rid">{r.active ? <CheckCircleOutlined /> : r.rule_set_id.slice(-6)}</span>
                              <span className="txt">
                                <Tag
                                  color={r.active ? 'success' : 'default'}
                                  style={{ marginRight: 6 }}
                                >
                                  {r.active ? '当前启用' : '未启用'}
                                </Tag>
                                {r.filename}
                                <div className="muted" style={{ marginTop: 2 }}>
                                  脚本 {r.script_count} · AI {r.ai_count}
                                  {r.scope_count ? ` · 范围 ${r.scope_count}` : ''}
                                  {r.unsupported_count ? ` · 待结构化 ${r.unsupported_count}` : ''}
                                  {r.warning_count ? ` · 警告 ${r.warning_count}` : ''}
                                </div>
                              </span>
                              <Tooltip title="启用该版本">
                                <Button
                                  type="text"
                                  size="small"
                                  icon={<CheckCircleOutlined />}
                                  disabled={r.active || running}
                                  onClick={() => handleActivateRuleSet(r.rule_set_id)}
                                />
                              </Tooltip>
                              <Popconfirm
                                title="删除该规则版本？"
                                description="会同时删除原始 Excel 和解析后的规则，删除后不可恢复。"
                                okText="删除"
                                cancelText="取消"
                                okButtonProps={{ danger: true }}
                                onConfirm={() => handleDeleteRuleSet(r.rule_set_id)}
                              >
                                <Tooltip title="删除该版本">
                                  <Button
                                    type="text"
                                    size="small"
                                    danger
                                    icon={<DeleteOutlined />}
                                    disabled={running}
                                  />
                                </Tooltip>
                              </Popconfirm>
                            </div>
                          ))
                        )}
                      </div>
                    </>
                  ),
                },
              ]}
            />
          </section>

          <section className="action-block upload-block">
            <div className="action-block-title">
              材料上传
              <Button
                size="small"
                icon={<ThunderboltOutlined />}
                onClick={handleLoadSamples}
              >
                一键载入样例
              </Button>
            </div>
            {isFollowupProcess ? (
              <div className="change-upload-grid">
                <div className="change-upload-section">
                  <div className="change-upload-title">上一次的初始/变更/更正登记申请模板</div>
                  <div className={currentUploads.some(isPreviousRegistrationUpload) ? 'dragger-compact' : ''}>
                    <Dragger
                      multiple
                      beforeUpload={(file) => handleUpload(file, '上一次登记申报模板')}
                      showUploadList={false}
                      accept=".json,.xlsx,.xlsm"
                    >
                      <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
                        <InboxOutlined />
                      </p>
                      <p style={{ fontSize: 13, color: 'var(--c-text)', margin: 0 }}>
                        上传上一次登记模板
                      </p>
                      <p style={{ fontSize: 12, color: 'var(--c-text-3)', margin: 0 }}>
                        支持 JSON / XLSX / XLSM
                      </p>
                    </Dragger>
                  </div>
                </div>
                <div className="change-upload-section">
                  <div className="change-upload-title">{followupProcessLabel}申请材料</div>
                  <div className={currentUploads.some(isChangeCurrentMaterial) ? 'dragger-compact' : ''}>
                    <Dragger
                      multiple
                      beforeUpload={handleFollowupRegistrationCurrentUpload}
                      showUploadList={false}
                      accept=".json,.pdf,.docx,.txt,.xlsx,.xlsm"
                    >
                      <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
                        <InboxOutlined />
                      </p>
                      <p style={{ fontSize: 13, color: 'var(--c-text)', margin: 0 }}>
                        上传本次{followupShortLabel}材料
                      </p>
                      <p style={{ fontSize: 12, color: 'var(--c-text-3)', margin: 0 }}>
                        模板 / 申请书 / 证明文件
                      </p>
                    </Dragger>
                  </div>
                </div>
              </div>
            ) : (
              <div className={currentUploads.length > 0 ? 'dragger-compact' : ''}>
                <Dragger
                  multiple
                  beforeUpload={(file) => handleUpload(file)}
                  showUploadList={false}
                  accept=".json,.pdf,.docx,.txt,.xlsx,.xlsm"
                >
                  <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
                    <InboxOutlined />
                  </p>
                  <p style={{ fontSize: 13, color: 'var(--c-text)', margin: 0 }}>
                    点击或拖拽上传材料
                  </p>
                  <p style={{ fontSize: 12, color: 'var(--c-text-3)', margin: 0 }}>
                    支持 JSON / PDF / DOCX / TXT
                    / XLSX / XLSM
                  </p>
                </Dragger>
              </div>
            )}
            {process === 'pre_registration_reapply' && (
              <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                原预登记材料为可选 baseline；上传后启用差异比对，不上传仍审核当前申报模板和本次材料。
              </div>
            )}
            {process === 'pre_registration_supplement' && (
              <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                补充说明材料用于补充事项说明；当前申报模板 JSON 仍为字段唯一数据源。
              </div>
            )}
            {process === 'change_general' && (
              <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                上一次登记模板仅作为历史参考；审核只依据本批规则判断本次变更材料。
              </div>
            )}
            {process === 'correction_general' && (
              <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                上一次登记模板仅作为历史参考；审核只依据本批规则判断本次更正材料。
              </div>
            )}
            {currentUploads.length > 0 && (
              <div className="upload-list compact">
                {currentUploads.map((u) => (
                  <div key={u.file_id} className="upload-item">
                    <span className="icn">📄</span>
                    <div className="meta">
                      <div className="name" title={u.original_name}>
                        {u.original_name}
                      </div>
                      <div className="sub">
                        {u.material_type && <Tag color="geekblue">{u.material_type}</Tag>}
                        {u.parse_status && (
                          <Tag color={u.parse_status === '已解析' ? 'success' : 'warning'}>
                            {u.parse_status}
                          </Tag>
                        )}
                        <span className="size">{fmtSize(u.size_bytes)}</span>
                      </div>
                    </div>
                    <Popconfirm
                      title="删除该文件？"
                      onConfirm={() => handleDelete(u.file_id)}
                    >
                      <Button
                        type="text"
                        size="small"
                        icon={<DeleteOutlined />}
                        danger
                      />
                    </Popconfirm>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="action-block start-block">
            <div className="action-block-title">开始审核</div>
            <div className="review-option-row">
              <div>
                <div className="review-option-title">材料片段裁剪</div>
                <div className="muted">优先发送规则相关片段，命中不足自动回退全文</div>
              </div>
              <Switch
                checked={materialSliceEnabled}
                onChange={(checked) => setMaterialSlice(checked, process)}
                disabled={running}
              />
            </div>
            {running ? (
              <Button
                danger
                block
                size="large"
                icon={<CloseCircleOutlined />}
                onClick={handleCancelReview}
                disabled={!jobId}
                style={{ marginTop: 12, fontWeight: 600 }}
              >
                取消审核
              </Button>
            ) : (
              <Button
                type="primary"
                block
                size="large"
                icon={<RocketOutlined />}
                onClick={handleStart}
                style={{ marginTop: 12, fontWeight: 600 }}
              >
                开始 AI 审核
              </Button>
            )}
            <div className="start-note">
              当前预览模板：
              <strong>{templateUpload?.original_name || '未上传申报模板'}</strong>
            </div>
            {process === 'pre_registration_reapply' && (
              <div className="start-note">
                baseline：
                <strong>{hasReapplyBaseline ? '已上传，启用差异比对' : '未上传，差异规则将跳过'}</strong>
              </div>
            )}
          </section>
        </div>
      </div>

      <div className="panel template-panel">
        <div className="panel-header">
          <h3>申报模板内容</h3>
          <div className="right">
            {templateMaterial && <Tag color="geekblue">{templateMaterial.material_name}</Tag>}
            {fieldIssues.length > 0 && <Tag color="error">字段问题 {fieldIssues.length}</Tag>}
          </div>
        </div>
        <div className="panel-body template-panel-body">
          {!templateUpload ? (
            <Empty description="暂无申报模板，请先上传或一键载入样例" style={{ padding: 48 }} />
          ) : templateLoading ? (
            <div className="template-empty-row">正在读取申报模板…</div>
          ) : !templateMaterial ? (
            <Empty description="申报模板未解析或解析失败" style={{ padding: 48 }} />
          ) : (
            <Collapse
              className="template-section-collapse"
              defaultActiveKey={[templateSections[0]?.name].filter(Boolean)}
              items={templateSections.map((section) => {
                const fieldCount = allSectionFields(section).length
                const issueCount = countSectionIssues(
                  section,
                  fieldIssues,
                  templateMaterial,
                  process,
                )
                return {
                  key: section.name,
                  label: (
                    <span className="template-section-label">
                      <span>{section.name}</span>
                      <span className="muted">
                        {`${fieldCount} 个字段`}
                      </span>
                      {issueCount > 0 && (
                        <span className="template-section-issue-count">
                          {`AI 标注 ${issueCount} 处异常`}
                        </span>
                      )}
                    </span>
                  ),
                  children: renderTemplateSection(section),
                }
              })}
            />
          )}
        </div>
      </div>

    </>
  )
}
