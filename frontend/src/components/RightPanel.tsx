import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Collapse, Empty, Popconfirm, Space, Switch, Tag, message } from 'antd'
import {
  CheckCircleOutlined,
  DeleteOutlined,
  DownloadOutlined,
  FilterOutlined,
  FolderOpenOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import jsPDF from 'jspdf'
import html2canvas from 'html2canvas'
import { useStore } from '../store'
import IssueCard from './IssueCard'
import ThreeStageLoading from './ThreeStageLoading'
import type { Issue } from '../types'

type R = '高风险' | '中风险' | '低风险'
const RISK_ORDER: Record<R, number> = { 高风险: 0, 中风险: 1, 低风险: 2 }

const DIMENSION_ORDER = [
  '登记必填要素规则库',
  '格式模板规则库',
  '跨材料数据逻辑校验库',
  '监管合规红线规则库',
  '业务退回/整改案例库',
  '审查风险分级规则库',
  '用户新增规则',
  '其他',
]

function normalizeDimension(raw?: string) {
  const text = (raw || '').replace(/\n/g, '').trim()
  if (!text) return '其他'
  return text.split('；')[0].split(';')[0].trim() || '其他'
}

function displayDimension(dim: string) {
  return dim.endsWith('规则库') ? dim.slice(0, -3) : dim
}

function dimensionSort(a: string, b: string) {
  const ai = DIMENSION_ORDER.indexOf(a)
  const bi = DIMENSION_ORDER.indexOf(b)
  const ar = ai === -1 ? 999 : ai
  const br = bi === -1 ? 999 : bi
  if (ar !== br) return ar - br
  return a.localeCompare(b, 'zh-Hans-CN')
}

export default function RightPanel() {
  const process = useStore((s) => s.process)
  const result = useStore((s) => s.resultByProcess[s.process])
  const rules = useStore((s) => s.rules)
  const jobStatus = useStore((s) => s.jobStatusByProcess[s.process])
  const progress = useStore((s) => s.progressByProcess[s.process])
  const batchProgress = useStore((s) => s.batchProgressByProcess[s.process])
  const clearReviewState = useStore((s) => s.clearReviewState)
  const filterRisks = useStore((s) => s.filterRisks)
  const toggleRisk = useStore((s) => s.toggleRisk)
  const exportRef = useRef<HTMLDivElement>(null)
  const [exporting, setExporting] = useState(false)
  const [filterDimensions, setFilterDimensions] = useState<Set<string>>(new Set())
  const [showDeduped, setShowDeduped] = useState(false)

  const running = jobStatus === 'pending' || jobStatus === 'running'
  const displayIssues =
    showDeduped && result?.deduped_issues?.length
      ? result.deduped_issues
      : result?.issues || []
  const displaySummary =
    showDeduped && result?.deduped_summary ? result.deduped_summary : result?.summary

  const sortedIssues = useMemo(() => {
    return [...displayIssues].sort(
      (a, b) => RISK_ORDER[a.risk_level as R] - RISK_ORDER[b.risk_level as R],
    )
  }, [displayIssues])

  const ruleDimensionMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const r of rules?.rules || []) {
      map.set(r.rule_id, normalizeDimension(r.review_dimension))
    }
    return map
  }, [rules])

  const allDimensions = useMemo(() => {
    const dims = new Set<string>()
    for (const r of rules?.rules || []) {
      dims.add(normalizeDimension(r.review_dimension))
    }
    for (const issue of displayIssues) {
      dims.add(
        normalizeDimension(
          issue.review_dimension || ruleDimensionMap.get(issue.rule_id),
        ),
      )
    }
    return Array.from(dims).sort(dimensionSort)
  }, [displayIssues, ruleDimensionMap, rules])

  useEffect(() => {
    setShowDeduped(false)
  }, [process, result])

  useEffect(() => {
    setFilterDimensions((prev) => {
      if (prev.size === 0) return prev
      const available = new Set(allDimensions)
      const next = new Set(Array.from(prev).filter((d) => available.has(d)))
      if (next.size === prev.size) return prev
      return next
    })
  }, [allDimensions])

  const activeDimensions = useMemo(() => {
    const available = new Set(allDimensions)
    const selected = Array.from(filterDimensions).filter((d) => available.has(d))
    return selected.length > 0 ? selected.sort(dimensionSort) : allDimensions
  }, [allDimensions, filterDimensions])

  const activeDimensionSet = useMemo(
    () => new Set(activeDimensions),
    [activeDimensions],
  )

  const riskFiltered = useMemo(
    () => sortedIssues.filter((i) => filterRisks.has(i.risk_level as R)),
    [sortedIssues, filterRisks],
  )

  const filtered = useMemo(
    () =>
      riskFiltered.filter((issue) =>
        activeDimensionSet.has(
          normalizeDimension(
            issue.review_dimension || ruleDimensionMap.get(issue.rule_id),
          ),
        ),
      ),
    [activeDimensionSet, riskFiltered, ruleDimensionMap],
  )

  const allIssuesByDimension = useMemo(() => {
    const grouped = new Map<string, Issue[]>()
    for (const issue of sortedIssues) {
      const dim = normalizeDimension(
        issue.review_dimension || ruleDimensionMap.get(issue.rule_id),
      )
      const items = grouped.get(dim) || []
      items.push(issue)
      grouped.set(dim, items)
    }
    return grouped
  }, [ruleDimensionMap, sortedIssues])

  const issuesByDimension = useMemo(() => {
    const grouped = new Map<string, Issue[]>()
    for (const issue of filtered) {
      const dim = normalizeDimension(
        issue.review_dimension || ruleDimensionMap.get(issue.rule_id),
      )
      const items = grouped.get(dim) || []
      items.push(issue)
      grouped.set(dim, items)
    }
    return grouped
  }, [filtered, ruleDimensionMap])

  const filteredIndexMap = useMemo(() => {
    const map = new Map<string, number>()
    filtered.forEach((issue, idx) => map.set(issue.issue_id, idx))
    return map
  }, [filtered])

  function toggleDimension(dim: string) {
    setFilterDimensions((prev) => {
      const next = new Set(prev)
      if (next.has(dim)) next.delete(dim)
      else next.add(dim)
      return next
    })
  }

  async function handleExportPDF() {
    if (!exportRef.current || !result) return
    setExporting(true)
    try {
      const el = exportRef.current
      const canvas = await html2canvas(el, {
        backgroundColor: '#ffffff',
        scale: 2,
        useCORS: true,
      })
      const imgData = canvas.toDataURL('image/png')
      const pdf = new jsPDF('p', 'mm', 'a4')
      const pdfW = pdf.internal.pageSize.getWidth()
      const pdfH = pdf.internal.pageSize.getHeight()
      const imgW = pdfW
      const imgH = (canvas.height * imgW) / canvas.width
      let heightLeft = imgH
      let position = 0
      pdf.addImage(imgData, 'PNG', 0, position, imgW, imgH)
      heightLeft -= pdfH
      while (heightLeft > 0) {
        position = heightLeft - imgH
        pdf.addPage()
        pdf.addImage(imgData, 'PNG', 0, position, imgW, imgH)
        heightLeft -= pdfH
      }
      const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-')
      pdf.save(`AI审核报告_${result.summary.registration_type}_${ts}.pdf`)
      message.success('已导出 PDF')
    } catch (e: any) {
      message.error('导出失败：' + (e?.message || ''))
    } finally {
      setExporting(false)
    }
  }

  // ===== 空态 =====
  if (jobStatus === 'idle' && !result) {
    return (
      <div className="panel" style={{ flex: 1 }}>
        <div className="panel-header">
          <h3><ThunderboltOutlined style={{ color: 'var(--c-primary)' }} /> AI 审核结果</h3>
        </div>
        <div className="empty-state">
          <div className="ico">📋</div>
          <div className="ttl">等待开始审核</div>
          <div className="sub">
            请先在左侧上传材料或一键载入样例，然后点击「开始 AI 审核」
          </div>
        </div>
      </div>
    )
  }

  // ===== Loading =====
  if (running) {
    const partialIssues = result?.issues || []
    const sortedPartial = [...partialIssues].sort(
      (a, b) => RISK_ORDER[a.risk_level as R] - RISK_ORDER[b.risk_level as R],
    )
    const { done, total } = batchProgress
    return (
      <div className="panel" style={{ flex: 1 }}>
        <div className="panel-header">
          <h3>
            <ThunderboltOutlined style={{ color: 'var(--c-primary)' }} /> AI 审核中…
          </h3>
          {total > 0 && (
            <div className="right">
              <Tag color="processing">
                {done}/{total} 批已完成
              </Tag>
              {partialIssues.length > 0 && (
                <Tag color="warning">已发现 {partialIssues.length} 个问题</Tag>
              )}
            </div>
          )}
        </div>
        <ThreeStageLoading />
        {sortedPartial.length > 0 && (
          <div
            style={{
              padding: '4px 18px 0',
              fontSize: 12,
              color: 'var(--c-text-2)',
            }}
          >
            👇 已收到的问题（最终合并版会在全部完成后替换显示）
          </div>
        )}
        <div className="panel-body" style={{ flex: 1, minHeight: 0 }}>
          {sortedPartial.map((iss, idx) => (
            <IssueCard
              key={iss.issue_id}
              index={idx}
              issue={iss}
              defaultOpen={idx < 2}
            />
          ))}
        </div>
        <div style={{ padding: '0 18px 18px' }}>
          <Collapse
            size="small"
            ghost
            items={[
              {
                key: 'log',
                label: (
                  <span style={{ fontSize: 12, color: 'var(--c-text-2)' }}>
                    🔍 过程日志（{progress.length} 条）
                  </span>
                ),
                children: (
                  <div className="progress-log">
                    {progress.length === 0 ? (
                      <span className="muted">等待开始…</span>
                    ) : (
                      progress.map((p, i) => (
                        <div className="line" key={i}>
                          <span className="ts">[{i.toString().padStart(2, '0')}]</span> {p}
                        </div>
                      ))
                    )}
                  </div>
                ),
              },
            ]}
          />
        </div>
      </div>
    )
  }

  // ===== 结果展示 =====
  if (!result) {
    return (
      <div className="panel">
        <div className="panel-header">
          <h3><ThunderboltOutlined style={{ color: 'var(--c-primary)' }} /> AI 审核结果</h3>
        </div>
        <Empty description="暂无审核结果" style={{ padding: 48 }} />
      </div>
    )
  }

  const { human_review_items, batch_logs } = result
  const summary = displaySummary || result.summary

  return (
    <div className="panel" style={{ flex: 1, minHeight: 0 }} ref={exportRef}>
      <div className="panel-header">
        <h3><ThunderboltOutlined style={{ color: 'var(--c-primary)' }} /> AI 审核结果 · {summary.registration_type}</h3>
        <div className="right">
          <Space>
            <Tag color="success">已完成</Tag>
            <Switch
              size="small"
              checked={showDeduped}
              onChange={setShowDeduped}
            />
            <span className="muted">合并去重</span>
            <Button
              size="small"
              type="primary"
              icon={<DownloadOutlined />}
              onClick={handleExportPDF}
              loading={exporting}
            >
              导出 PDF
            </Button>
            <Popconfirm
              title="清除当前流程的审核结果?"
              description="该操作只影响当前流程,另一个流程的结果不会受影响"
              okText="清除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => {
                clearReviewState(process)
                message.success('已清除当前流程的审核结果')
              }}
            >
              <Button size="small" danger icon={<DeleteOutlined />}>
                清除
              </Button>
            </Popconfirm>
          </Space>
        </div>
      </div>

      {/* Stats 横条 */}
      <div className="stats-bar">
        <div className="stat total">
          <div className="num">{summary.total_issues}</div>
          <div className="lbl">问题总数</div>
        </div>
        <div className="stat high">
          <div className="num">{summary.high_risk_count}</div>
          <div className="lbl">高风险</div>
        </div>
        <div className="stat mid">
          <div className="num">{summary.medium_risk_count}</div>
          <div className="lbl">中风险</div>
        </div>
        <div className="stat low">
          <div className="num">{summary.low_risk_count}</div>
          <div className="lbl">低风险</div>
        </div>
      </div>

      {/* 筛选栏 */}
      <div className="filter-bar">
        <div className="filter-row">
          <FilterOutlined style={{ color: 'var(--c-text-2)' }} />
          <span className="lbl">按风险筛选：</span>
          {(['高风险', '中风险', '低风险'] as R[]).map((r) => {
            const active = filterRisks.has(r)
            const cls = r === '高风险' ? 'high' : r === '中风险' ? 'mid' : 'low'
            return (
              <span
                key={r}
                className={`filter-chip ${cls} ${active ? 'active' : ''}`}
                onClick={() => toggleRisk(r)}
              >
                {active ? '✓ ' : ''}
                {r}
              </span>
            )
          })}
          <div className="right">
            <span className="muted">显示 {filtered.length} / {sortedIssues.length} 条</span>
          </div>
        </div>
        <div className="filter-row">
          <span className="lbl">按审核类别筛选：</span>
          <span
            className={`filter-chip dimension ${filterDimensions.size === 0 ? 'active' : ''}`}
            onClick={() => setFilterDimensions(new Set())}
          >
            全部类别
          </span>
          {allDimensions.map((dim) => {
            const active = filterDimensions.has(dim)
            return (
              <span
                key={dim}
                className={`filter-chip dimension ${active ? 'active' : ''}`}
                onClick={() => toggleDimension(dim)}
              >
                {active ? '✓ ' : ''}
                {displayDimension(dim)}
              </span>
            )
          })}
        </div>
      </div>

      <div className="panel-body" style={{ flex: 1, minHeight: 0 }}>
        {activeDimensions.length === 0 ? (
          <Empty description="暂无可展示的审核维度" style={{ padding: 24 }} />
        ) : (
          <div className="dimension-groups">
            {activeDimensions.map((dim) => {
              const issues = issuesByDimension.get(dim) || []
              const totalInDim = allIssuesByDimension.get(dim)?.length || 0
              const passed = totalInDim === 0
              const title = displayDimension(dim)

              return (
                <Collapse
                  key={dim}
                  className={`dimension-collapse ${passed ? 'passed' : ''}`}
                  defaultActiveKey={passed ? [] : [dim]}
                  items={[
                    {
                      key: dim,
                      label: (
                        <span className="dimension-label">
                          <span className="dimension-title">
                            {title}
                            {passed ? '（通过）' : `（${totalInDim}条）`}
                          </span>
                          {!passed && issues.length !== totalInDim && (
                            <span className="dimension-filter-note">
                              当前筛选显示 {issues.length} 条
                            </span>
                          )}
                        </span>
                      ),
                      children: passed ? (
                        <div className="dimension-pass">
                          <CheckCircleOutlined />
                          <span>AI 审查通过，未发现{title}问题。</span>
                        </div>
                      ) : issues.length === 0 ? (
                        <Empty
                          description="当前风险筛选下暂无该类别问题"
                          style={{ padding: 16 }}
                        />
                      ) : (
                        issues.map((iss) => {
                          const displayIndex = filteredIndexMap.get(iss.issue_id) ?? 0
                          return (
                            <IssueCard
                              key={iss.issue_id}
                              index={displayIndex}
                              issue={iss}
                              defaultOpen={displayIndex < 2}
                            />
                          )
                        })
                      ),
                    },
                  ]}
                />
              )
            })}
          </div>
        )}

        {/* 需人工复核 */}
        {human_review_items && human_review_items.length > 0 && (
          <Collapse
            size="small"
            ghost
            style={{ marginTop: 8 }}
            items={[
              {
                key: 'human',
                label: (
                  <span style={{ fontSize: 13, fontWeight: 600 }}>
                    👀 需人工复核（{human_review_items.length} 条，AI 不可靠的规则）
                  </span>
                ),
                children: (
                  <div>
                    {human_review_items.map((h) => (
                      <div key={h.rule_id} className="rule-row">
                        <span className="rid">{h.rule_id}</span>
                        <span className="txt">
                          <strong>{h.rule_name}</strong>
                          <span style={{ color: 'var(--c-text-3)', marginLeft: 6 }}>
                            · {h.reason}
                          </span>
                          <div className="muted" style={{ marginTop: 2 }}>
                            {h.rule_text}
                          </div>
                        </span>
                      </div>
                    ))}
                  </div>
                ),
              },
            ]}
          />
        )}

        {/* 过程日志（默认折叠） */}
        <Collapse
          size="small"
          ghost
          style={{ marginTop: 8 }}
          items={[
            {
              key: 'log',
              label: (
                <span style={{ fontSize: 12, color: 'var(--c-text-2)' }}>
                  <FolderOpenOutlined /> 过程日志（{progress.length} 条，含 {batch_logs.length} 个批次）
                </span>
              ),
              children: (
                <>
                  <div className="progress-log" style={{ marginBottom: 10 }}>
                    {progress.map((p, i) => (
                      <div className="line" key={i}>
                        <span className="ts">[{i.toString().padStart(2, '0')}]</span> {p}
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--c-text-2)' }}>
                    <strong>批次明细：</strong>
                    {batch_logs.map((b) => (
                      <div key={b.batch_id} style={{ marginTop: 4 }}>
                        <Tag color={b.status === 'success' ? 'success' : 'error'}>
                          {b.batch_id}
                        </Tag>
                        {b.review_dimension}（{b.rule_count} 条规则） ·{' '}
                        {b.issues_found} 个问题 · {b.duration_seconds.toFixed(2)}s ·
                        tokens {b.input_tokens}/{b.output_tokens}
                        {b.slice_enabled && (
                          <span>
                            {' '}· 裁剪 {b.original_segment_count}→{b.sliced_segment_count}
                            {b.slice_fallback ? '（含回退）' : ''}
                            {b.slice_confidence ? ` · ${b.slice_confidence}` : ''}
                          </span>
                        )}
                        {b.error && (
                          <span style={{ color: 'var(--c-risk-high)' }}> · {b.error}</span>
                        )}
                        {b.slice_summary && (
                          <div className="muted" style={{ marginTop: 2, marginLeft: 48 }}>
                            {b.slice_summary}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              ),
            },
          ]}
        />
      </div>
    </div>
  )
}
