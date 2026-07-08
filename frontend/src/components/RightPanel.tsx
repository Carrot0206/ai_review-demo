import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Collapse, Empty, Popconfirm, Space, Switch, Tag, message } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  DownloadOutlined,
  FilterOutlined,
  FolderOpenOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useStore } from '../store'
import IssueCard from './IssueCard'
import ThreeStageLoading from './ThreeStageLoading'
import type { Issue, RuleBasis } from '../types'

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

function isRiskHint(issue: Issue) {
  return issue.severity_type === 'risk_hint'
}

function escapeHtml(raw: string | number | null | undefined) {
  return String(raw ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

const REVIEW_METHOD_MARK_PREFIX = '__review_method__:'

function basisTextWithoutMethod(text: string) {
  if (!text.startsWith(REVIEW_METHOD_MARK_PREFIX)) return text
  const index = text.indexOf('\n')
  return index >= 0 ? text.slice(index + 1) : ''
}

function issueMethodLabel(issue: Issue) {
  const bases = issue.rule_bases?.length ? issue.rule_bases : [issue.rule_basis]
  const marker = bases
    .map((basis) => (basis?.rule_text || '').trim())
    .find((text) => text.startsWith(REVIEW_METHOD_MARK_PREFIX))
  if (!marker) return 'AI'
  return marker.slice(REVIEW_METHOD_MARK_PREFIX.length).split('\n')[0].trim() === '脚本'
    ? '脚本'
    : 'AI'
}

function plainBasisText(b: RuleBasis) {
  const file = (b.basis_file || '').trim()
  const text = basisTextWithoutMethod((b.rule_text || '').trim())
  const isUser = b.basis_type === '用户新增规则' || file === '用户新增规则' || !file
  return isUser ? text : `《${file}》：${text}`
}

function issueLocationsOverlap(a: Issue, b: Issue) {
  const left = a.issue_location || []
  const right = b.issue_location || []
  return left.some((locA) =>
    right.some(
      (locB) =>
        locA.material_name === locB.material_name &&
        locA.location === locB.location,
    ),
  )
}

function issueContainsSourceIssue(displayIssue: Issue, sourceIssue: Issue) {
  const ruleMatch =
    displayIssue.rule_id === sourceIssue.rule_id ||
    (displayIssue.rule_ids || []).includes(sourceIssue.rule_id)
  if (!ruleMatch) return false
  if (issueLocationsOverlap(displayIssue, sourceIssue)) return true
  if (displayIssue.issue_summary === sourceIssue.issue_summary) return true
  return (displayIssue.alt_summaries || []).includes(sourceIssue.issue_summary)
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
  const selectedIssueId = useStore((s) => s.selectedIssueIdByProcess[s.process])
  const selectedIssueNonce = useStore((s) => s.selectedIssueNonceByProcess[s.process])
  const setSelectedIssue = useStore((s) => s.setSelectedIssue)
  const clearSelectedIssue = useStore((s) => s.clearSelectedIssue)
  const showDeduped = useStore((s) => s.showDedupedByProcess[s.process])
  const setShowDeduped = useStore((s) => s.setShowDeduped)
  const issueRefs = useRef(new Map<string, HTMLDivElement>())
  const [exporting, setExporting] = useState(false)
  const [filterDimensions, setFilterDimensions] = useState<Set<string>>(new Set())

  const running = jobStatus === 'pending' || jobStatus === 'running'
  const displayIssues = useMemo(
    () =>
      showDeduped && result?.deduped_issues?.length
        ? result.deduped_issues
        : result?.issues || [],
    [result, showDeduped],
  )
  const displaySummary = useMemo(
    () => (showDeduped && result?.deduped_summary ? result.deduped_summary : result?.summary),
    [result, showDeduped],
  )

  const sortedIssues = useMemo(() => {
    return displayIssues.filter((issue) => !isRiskHint(issue)).sort(
      (a, b) => RISK_ORDER[a.risk_level as R] - RISK_ORDER[b.risk_level as R],
    )
  }, [displayIssues])

  const sortedRiskHints = useMemo(() => {
    return displayIssues.filter(isRiskHint).sort(
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
      if (r.severity_type === 'risk_hint') continue
      dims.add(normalizeDimension(r.review_dimension))
    }
    for (const issue of sortedIssues) {
      dims.add(
        normalizeDimension(
          issue.review_dimension || ruleDimensionMap.get(issue.rule_id),
        ),
      )
    }
    return Array.from(dims).sort(dimensionSort)
  }, [ruleDimensionMap, rules, sortedIssues])

  useEffect(() => {
    setShowDeduped(false, process)
  }, [process, result, setShowDeduped])

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

  const selectableIssueIds = useMemo(
    () => new Set([...filtered, ...sortedRiskHints].map((issue) => issue.issue_id)),
    [filtered, sortedRiskHints],
  )

  useEffect(() => {
    if (!selectedIssueId) return
    if (!selectableIssueIds.has(selectedIssueId)) {
      const sourceIssue = result?.issues?.find((issue) => issue.issue_id === selectedIssueId)
      const mappedIssue =
        showDeduped && sourceIssue
          ? filtered.find((issue) => issueContainsSourceIssue(issue, sourceIssue))
          : null
      if (mappedIssue) {
        setSelectedIssue(mappedIssue.issue_id, process)
        return
      }
      clearSelectedIssue(process)
      return
    }
    window.requestAnimationFrame(() => {
      const node = issueRefs.current.get(selectedIssueId)
      node?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }, [
    clearSelectedIssue,
    filtered,
    process,
    result,
    selectableIssueIds,
    selectedIssueId,
    selectedIssueNonce,
    setSelectedIssue,
    showDeduped,
  ])

  function handleSelectIssue(issue: Issue) {
    setSelectedIssue(issue.issue_id, process)
  }

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

  function toggleDimension(dim: string) {
    setFilterDimensions((prev) => {
      const next = new Set(prev)
      if (next.has(dim)) next.delete(dim)
      else next.add(dim)
      return next
    })
  }

function buildIssueCardHtml(issue: Issue, index: number) {
    const locations = issue.issue_location || []
    const allBases = issue.rule_bases?.length ? issue.rule_bases : [issue.rule_basis]
    const allSummaries = [issue.issue_summary, ...(issue.alt_summaries || [])].filter(Boolean)
    const allSuggestions = [issue.suggestion, ...(issue.alt_suggestions || [])].filter(Boolean)
    const ruleIds = issue.rule_ids?.length ? issue.rule_ids : [issue.rule_id]
    const dim = normalizeDimension(
      issue.review_dimension || ruleDimensionMap.get(issue.rule_id),
    )
    const method = issueMethodLabel(issue)

    const locationsHtml =
      locations.length === 0
        ? `<div class="content">${allSummaries
            .map((s, i) => `<p>${allSummaries.length > 1 ? `[${i + 1}] ` : ''}${escapeHtml(s)}</p>`)
            .join('')}<p class="muted">未定位到具体字段</p></div>`
        : locations
            .map((loc, i) => {
              const reason = allSummaries[i] || allSummaries[0] || issue.issue_summary
              return `
                <div class="location-block">
                  <div class="material">📄 ${escapeHtml(loc.material_name)}</div>
                  <div>路径：<code>${escapeHtml(loc.location)}</code></div>
                  <div>取值：<code class="value">${escapeHtml(loc.value)}</code></div>
                  <div class="reason">原因：${escapeHtml(reason)}</div>
                </div>
              `
            })
            .join('')

    const basesHtml = allBases
      .map((b) => {
        const isUser =
          b?.basis_type === '用户新增规则' ||
          (b?.basis_file || '').trim() === '用户新增规则'
        return `
          <div class="basis-item">
            <div class="muted">${isUser ? '· 用户新增规则' : '· 内置规则'}</div>
            <div>${escapeHtml(plainBasisText(b))}</div>
          </div>
        `
      })
      .join('')

    const suggestionsHtml =
      allSuggestions.length === 0
        ? '<span class="muted">（无）</span>'
        : allSuggestions
            .map((s, i) => `<p>${allSuggestions.length > 1 ? `[${i + 1}] ` : ''}${escapeHtml(s)}</p>`)
            .join('')

    return `
      <section class="issue-card ${issue.risk_level}">
        <div class="issue-title-row">
          <div>
            <span class="issue-no">#${index + 1}</span>
            <span class="issue-title">${escapeHtml(issue.issue_summary)}</span>
          </div>
          <div class="tags">
            <span class="method ${method === '脚本' ? 'script' : 'ai'}">${escapeHtml(method)}</span>
            <span class="risk">${escapeHtml(isRiskHint(issue) ? '风险提示' : issue.risk_level)}</span>
          </div>
        </div>
        <div class="meta">
          审核类别：${escapeHtml(displayDimension(dim))}　
          问题编号：${escapeHtml(issue.issue_id)}　
          规则ID：${escapeHtml(ruleIds.join('、'))}
        </div>
        <h4>① 问题点位</h4>
        ${locationsHtml}
        <h4>② 规则依据</h4>
        ${basesHtml}
        <h4>③ ${isRiskHint(issue) ? '重点关注建议' : 'AI 整改建议'}</h4>
        <div class="suggestion">${suggestionsHtml}</div>
      </section>
    `
  }

  function buildPrintableReportHtml() {
    if (!result) return ''
    const summary = displaySummary || result.summary
    const exportIssues = [...sortedIssues]
    const exportRiskHints = [...sortedRiskHints]
    const generatedAt = new Date().toLocaleString('zh-CN')
    const mode = showDeduped ? '合并去重版' : '原始命中版'
    const cardsHtml = exportIssues.length
      ? exportIssues.map((issue, idx) => buildIssueCardHtml(issue, idx)).join('')
      : '<div class="empty">未发现审核问题。</div>'

    const riskHintsHtml = exportRiskHints.length
      ? `
        <h2>风险提示/重点关注（${exportRiskHints.length} 条，不计入问题总数）</h2>
        ${exportRiskHints.map((issue, idx) => buildIssueCardHtml(issue, idx)).join('')}
      `
      : ''

    const humanHtml = result.human_review_items?.length
      ? `
        <section class="human-section">
          <h2>需人工复核规则（${result.human_review_items.length} 条）</h2>
          ${result.human_review_items
            .map(
              (item) => `
                <div class="human-item">
                  <strong>${escapeHtml(item.rule_id)} ${escapeHtml(item.rule_name)}</strong>
                  <p>原因：${escapeHtml(item.reason)}</p>
                  <p>${escapeHtml(item.rule_text)}</p>
                </div>
              `,
            )
            .join('')}
        </section>
      `
      : ''

    return `<!doctype html>
      <html>
        <head>
          <meta charset="utf-8" />
          <title>AI审核报告_${escapeHtml(summary.registration_type)}</title>
          <style>
            @page { size: A4; margin: 14mm; }
            * { box-sizing: border-box; }
            body {
              margin: 0;
              color: #111827;
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif;
              font-size: 12px;
              line-height: 1.65;
              background: #fff;
            }
            h1 { margin: 0 0 8px; font-size: 22px; }
            h2 { margin: 22px 0 10px; font-size: 16px; }
            h4 { margin: 12px 0 6px; font-size: 12px; color: #374151; }
            p { margin: 0 0 4px; }
            code {
              font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
              white-space: pre-wrap;
              word-break: break-word;
              color: #991b1b;
            }
            .report-meta { color: #6b7280; margin-bottom: 14px; }
            .summary {
              display: grid;
              grid-template-columns: repeat(5, 1fr);
              gap: 8px;
              margin: 12px 0 18px;
            }
            .summary .cell {
              border: 1px solid #e5e7eb;
              border-radius: 6px;
              padding: 8px;
              background: #f9fafb;
            }
            .summary .num { font-size: 18px; font-weight: 700; }
            .issue-card {
              page-break-inside: avoid;
              border: 1px solid #e5e7eb;
              border-left-width: 4px;
              border-radius: 8px;
              padding: 12px;
              margin: 0 0 12px;
            }
            .issue-card.高风险 { border-left-color: #dc2626; }
            .issue-card.中风险 { border-left-color: #d97706; }
            .issue-card.低风险 { border-left-color: #059669; }
            .issue-title-row {
              display: flex;
              justify-content: space-between;
              gap: 12px;
              align-items: flex-start;
              margin-bottom: 6px;
            }
            .issue-no { color: #6b7280; margin-right: 8px; }
            .issue-title { font-weight: 700; font-size: 14px; }
            .risk {
              flex: 0 0 auto;
              border: 1px solid #d1d5db;
              border-radius: 999px;
              padding: 1px 8px;
              font-weight: 600;
              background: #fff;
            }
            .tags {
              display: flex;
              align-items: center;
              gap: 6px;
              flex: 0 0 auto;
            }
            .method {
              border-radius: 999px;
              padding: 1px 8px;
              font-weight: 700;
            }
            .method.ai { color: #4A54A8; background: #EEF2FF; }
            .method.script { color: #047857; background: #DFF8EA; }
            .meta, .muted { color: #6b7280; }
            .location-block, .basis-item, .suggestion, .human-item {
              border: 1px solid #e5e7eb;
              border-radius: 6px;
              padding: 8px;
              margin-bottom: 6px;
              background: #fff;
            }
            .material { color: #6b7280; margin-bottom: 3px; }
            .reason {
              border-top: 1px dashed #e5e7eb;
              margin-top: 6px;
              padding-top: 6px;
            }
            .human-section { page-break-before: auto; }
            .empty {
              border: 1px dashed #d1d5db;
              border-radius: 8px;
              padding: 18px;
              color: #6b7280;
            }
          </style>
        </head>
        <body>
          <h1>AI 审核报告 - ${escapeHtml(summary.registration_type)}</h1>
          <div class="report-meta">
            导出时间：${escapeHtml(generatedAt)}　
            导出范围：${escapeHtml(mode)}全部问题（不受页面筛选影响）
          </div>
          <div class="summary">
            <div class="cell"><div class="num">${summary.total_issues}</div><div>问题总数</div></div>
            <div class="cell"><div class="num">${summary.high_risk_count}</div><div>高风险</div></div>
            <div class="cell"><div class="num">${summary.medium_risk_count}</div><div>中风险</div></div>
            <div class="cell"><div class="num">${summary.low_risk_count}</div><div>低风险</div></div>
            <div class="cell"><div class="num">${summary.risk_hint_count || exportRiskHints.length}</div><div>风险提示</div></div>
          </div>
          <h2>审核问题（${exportIssues.length} 条）</h2>
          ${cardsHtml}
          ${riskHintsHtml}
          ${humanHtml}
        </body>
      </html>`
  }

  function handleExportPDF() {
    if (!result) return
    setExporting(true)
    try {
      const iframe = document.createElement('iframe')
      iframe.style.position = 'fixed'
      iframe.style.right = '0'
      iframe.style.bottom = '0'
      iframe.style.width = '0'
      iframe.style.height = '0'
      iframe.style.border = '0'
      iframe.setAttribute('aria-hidden', 'true')
      document.body.appendChild(iframe)

      const doc = iframe.contentDocument
      const win = iframe.contentWindow
      if (!doc || !win) {
        throw new Error('无法创建打印窗口')
      }
      doc.open()
      doc.write(buildPrintableReportHtml())
      doc.close()

      setTimeout(() => {
        win.focus()
        win.print()
        setTimeout(() => {
          iframe.remove()
        }, 60_000)
      }, 200)
      message.success('已生成文字版报告，请在打印窗口选择“另存为 PDF”')
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
          <h3><ThunderboltOutlined style={{ color: 'var(--c-primary)' }} /> AI 审查结果</h3>
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

  if (jobStatus === 'cancelled' && !result) {
    return (
      <div className="panel" style={{ flex: 1 }}>
        <div className="panel-header">
          <h3><ThunderboltOutlined style={{ color: 'var(--c-primary)' }} /> AI 审查结果</h3>
        </div>
        <div className="empty-state">
          <div className="ico"><CloseCircleOutlined /></div>
          <div className="ttl">审核已取消</div>
          <div className="sub">本次审核已停止，可以重新点击「开始 AI 审核」发起新任务。</div>
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
              ref={(node) => {
                if (node) issueRefs.current.set(iss.issue_id, node)
                else issueRefs.current.delete(iss.issue_id)
              }}
              forceOpen={selectedIssueId === iss.issue_id}
              selected={selectedIssueId === iss.issue_id}
              onSelect={() => handleSelectIssue(iss)}
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
          <h3><ThunderboltOutlined style={{ color: 'var(--c-primary)' }} /> AI 审查结果</h3>
        </div>
        <Empty description="暂无审核结果" style={{ padding: 48 }} />
      </div>
    )
  }

  const { human_review_items, batch_logs } = result
  const summary = displaySummary || result.summary

  return (
    <div className="panel" style={{ flex: 1, minHeight: 0 }}>
      <div className="review-result-head">
        <div className="review-result-title-row">
          <h3>
            <ThunderboltOutlined style={{ color: 'var(--c-primary)' }} /> AI 审查结果
          </h3>
          <div className="dedupe-control">
            <span className="muted">合并去重</span>
            <Switch
              size="small"
              checked={showDeduped}
              onChange={(checked) => setShowDeduped(checked, process)}
            />
          </div>
        </div>
        <div className="review-result-actions">
          <Tag color="success">已完成</Tag>
          <Space size={8}>
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
                issueRefs.current.clear()
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
        <div className="stat">
          <div className="num">{summary.risk_hint_count || sortedRiskHints.length}</div>
          <div className="lbl">风险提示</div>
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
                        issues.map((iss, idx) => (
                          <IssueCard
                            key={iss.issue_id}
                            index={idx}
                            issue={iss}
                            ref={(node) => {
                              if (node) issueRefs.current.set(iss.issue_id, node)
                              else issueRefs.current.delete(iss.issue_id)
                            }}
                            forceOpen={selectedIssueId === iss.issue_id}
                            selected={selectedIssueId === iss.issue_id}
                            onSelect={() => handleSelectIssue(iss)}
                          />
                        ))
                      ),
                    },
                  ]}
                />
              )
            })}
          </div>
        )}

        {sortedRiskHints.length > 0 && (
          <Collapse
            size="small"
            ghost
            style={{ marginTop: 8 }}
            items={[
              {
                key: 'risk-hints',
                label: (
                  <span style={{ fontSize: 13, fontWeight: 600 }}>
                    风险提示/重点关注（{sortedRiskHints.length} 条，不计入问题总数）
                  </span>
                ),
                children: (
                  <div>
                    {sortedRiskHints.map((iss, idx) => (
                      <IssueCard
                        key={iss.issue_id}
                        index={idx}
                        issue={iss}
                        ref={(node) => {
                          if (node) issueRefs.current.set(iss.issue_id, node)
                          else issueRefs.current.delete(iss.issue_id)
                        }}
                        forceOpen={selectedIssueId === iss.issue_id}
                        selected={selectedIssueId === iss.issue_id}
                        onSelect={() => handleSelectIssue(iss)}
                      />
                    ))}
                  </div>
                ),
              },
            ]}
          />
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
