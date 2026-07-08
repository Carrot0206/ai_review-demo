import { forwardRef, useEffect, useState } from 'react'
import { DownOutlined } from '@ant-design/icons'
import type { Issue, RuleBasis } from '../types'

function riskClass(level: string) {
  if (level === '高风险') return 'high'
  if (level === '中风险') return 'mid'
  return 'low'
}

const REVIEW_METHOD_MARK_PREFIX = '__review_method__:'

function basisTextWithoutMethod(text: string) {
  if (!text.startsWith(REVIEW_METHOD_MARK_PREFIX)) return text
  const index = text.indexOf('\n')
  return index >= 0 ? text.slice(index + 1) : ''
}

function methodLabel(issue: Issue) {
  const bases = issue.rule_bases?.length ? issue.rule_bases : [issue.rule_basis]
  const marker = bases
    .map((basis) => (basis?.rule_text || '').trim())
    .find((text) => text.startsWith(REVIEW_METHOD_MARK_PREFIX))
  if (!marker) return 'AI'
  return marker.slice(REVIEW_METHOD_MARK_PREFIX.length).split('\n')[0].trim() === '脚本'
    ? '脚本'
    : 'AI'
}

/** 根据 basis 渲染：《文件》：规则内容；用户新增/无文件时只显示 rule_text。 */
function renderBasisLine(b: RuleBasis) {
  const file = (b.basis_file || '').trim()
  const text = basisTextWithoutMethod((b.rule_text || '').trim())
  const isUser = b.basis_type === '用户新增规则' || file === '用户新增规则' || !file
  if (isUser || !file) {
    return <span>{text}</span>
  }
  return (
    <span>
      <span style={{ fontWeight: 600 }}>《{file}》</span>
      <span style={{ margin: '0 4px', color: 'var(--c-text-3)' }}>：</span>
      <span>{text}</span>
    </span>
  )
}

function recordLabelFromLocation(location: string) {
  const match = (location || '').match(/\[(\d+)\]/)
  if (!match) return ''
  const n = Number(match[1])
  if (!Number.isFinite(n) || n <= 0) return ''
  const chinese = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
  const label = n <= 10 ? chinese[n] : String(n)
  return `第${label}条`
}

function shouldShowRecordLabel(recordLabel: string, reason: string) {
  if (!recordLabel) return false
  return !(reason || '').includes(recordLabel)
}

interface Props {
  index: number
  issue: Issue
  defaultOpen?: boolean
  forceOpen?: boolean
  selected?: boolean
  onSelect?: (issueId: string) => void
}

const IssueCard = forwardRef<HTMLDivElement, Props>(function IssueCard(
  { issue, defaultOpen = false, forceOpen = false, selected = false, onSelect },
  ref,
) {
  const [open, setOpen] = useState(defaultOpen)
  const cls = riskClass(issue.risk_level)
  const locations = issue.issue_location || []
  const allBases = issue.rule_bases?.length ? issue.rule_bases : [issue.rule_basis]
  const allSummaries = [issue.issue_summary, ...(issue.alt_summaries || [])]
  const allSuggestions = [issue.suggestion, ...(issue.alt_suggestions || [])].filter(Boolean)
  const isRiskHint = issue.severity_type === 'risk_hint'

  useEffect(() => {
    if (forceOpen) setOpen(true)
  }, [forceOpen])

  return (
    <div className={`issue-card ${cls} ${selected ? 'selected' : ''}`} ref={ref}>
      <div
        className="issue-head"
        onClick={() => {
          onSelect?.(issue.issue_id)
          setOpen((v) => !v)
        }}
      >
        <span className="title" title={issue.issue_summary}>
          {issue.issue_summary}
        </span>
        <span className={`method-tag ${methodLabel(issue) === '脚本' ? 'script' : 'ai'}`}>
          {methodLabel(issue)}
        </span>
        <span className={`risk-tag ${cls}`}>
          {isRiskHint ? '风险提示' : issue.risk_level}
        </span>
        <DownOutlined className={`chev ${open ? 'open' : ''}`} />
      </div>
      {open && (
        <div className="issue-body">
          {/* 1. 问题点位（合并 原问题原因 + 原问题点位） */}
          <div className="issue-section">
            <div className="label">① 问题点位</div>
            {locations.length === 0 ? (
              <div className="content">
                {allSummaries.map((s, i) => (
                  <div key={i} style={{ marginBottom: i < allSummaries.length - 1 ? 6 : 0 }}>
                    {allSummaries.length > 1 && (
                      <span style={{ color: 'var(--c-text-3)', marginRight: 4 }}>
                        [{i + 1}]
                      </span>
                    )}
                    {s}
                  </div>
                ))}
                <div className="muted" style={{ marginTop: 6 }}>未定位到具体字段</div>
              </div>
            ) : (
              locations.map((loc, i) => {
                const reason = allSummaries[i] || allSummaries[0]
                const recordLabel = recordLabelFromLocation(loc.location)
                const showRecordLabel = shouldShowRecordLabel(recordLabel, reason)
                return (
                  <div className="content" key={i} style={{ marginBottom: 6 }}>
                    <div style={{ fontSize: 12, color: 'var(--c-text-3)' }}>
                      📄 {loc.material_name}
                    </div>
                    <div style={{ marginTop: 4 }}>
                      路径：<code>{loc.location}</code>
                    </div>
                    <div style={{ marginTop: 4 }}>
                      取值：<code style={{ background: '#FEE2E2', color: '#DC2626' }}>{loc.value}</code>
                    </div>
                    <div
                      style={{
                        marginTop: 6,
                        paddingTop: 6,
                        borderTop: '1px dashed var(--c-border)',
                        color: 'var(--c-text)',
                      }}
                    >
                      <span style={{ color: 'var(--c-text-3)', marginRight: 4 }}>
                        原因：
                      </span>
                      {showRecordLabel && (
                        <span style={{ fontWeight: 600, marginRight: 4 }}>
                          {recordLabel}
                        </span>
                      )}
                      {reason}
                    </div>
                  </div>
                )
              })
            )}
          </div>

          {/* 2. 规则依据 */}
          <div className="issue-section">
            <div className="label">② 规则依据</div>
            {allBases.map((b, i) => {
              const isUser =
                b?.basis_type === '用户新增规则' ||
                (b?.basis_file || '').trim() === '用户新增规则'
              return (
                <div className="content basis" key={i} style={{ marginBottom: 6 }}>
                  <div style={{ marginBottom: 4, color: 'var(--c-text-3)' }}>
                    {isUser ? '· 用户新增规则' : '· 内置规则'}
                  </div>
                  <div>{renderBasisLine(b)}</div>
                </div>
              )
            })}
          </div>

          {/* 3. AI 整改建议 */}
          <div className="issue-section">
            <div className="label">③ {isRiskHint ? '重点关注建议' : 'AI 整改建议'}</div>
            <div className="content suggestion">
              {allSuggestions.length === 0 ? (
                <span className="muted">（无）</span>
              ) : (
                allSuggestions.map((s, i) => (
                  <div key={i} style={{ marginBottom: i < allSuggestions.length - 1 ? 6 : 0 }}>
                    {allSuggestions.length > 1 && (
                      <span style={{ color: 'var(--c-text-3)', marginRight: 4 }}>
                        [{i + 1}]
                      </span>
                    )}
                    {s}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
})

export default IssueCard
