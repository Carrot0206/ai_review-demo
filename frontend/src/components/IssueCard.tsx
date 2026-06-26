import { useState } from 'react'
import { DownOutlined } from '@ant-design/icons'
import type { Issue } from '../types'

function riskClass(level: string) {
  if (level === '高风险') return 'high'
  if (level === '中风险') return 'mid'
  return 'low'
}

interface Props {
  index: number
  issue: Issue
  defaultOpen?: boolean
}

export default function IssueCard({ index, issue, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen)
  const cls = riskClass(issue.risk_level)
  const locations = issue.issue_location || []
  const allBases = issue.rule_bases?.length ? issue.rule_bases : [issue.rule_basis]
  const allSummaries = [issue.issue_summary, ...(issue.alt_summaries || [])]
  const allSuggestions = [issue.suggestion, ...(issue.alt_suggestions || [])].filter(Boolean)

  return (
    <div className={`issue-card ${cls}`}>
      <div className="issue-head" onClick={() => setOpen((v) => !v)}>
        <span className="seq">#{index + 1}</span>
        <span className={`risk-tag ${cls}`}>
          {issue.risk_level}
        </span>
        <span className="title" title={issue.issue_summary}>
          {issue.issue_summary}
        </span>
        <DownOutlined className={`chev ${open ? 'open' : ''}`} />
      </div>
      {open && (
        <div className="issue-body">
          {/* 1. 问题原因 */}
          <div className="issue-section">
            <div className="label">① 问题原因</div>
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
            </div>
          </div>

          {/* 2. 风险等级 */}
          <div className="issue-section">
            <div className="label">② 风险等级</div>
            <div className="content">
              <span className={`risk-tag ${cls}`}>{issue.risk_level}</span>
              <span style={{ marginLeft: 10, color: 'var(--c-text-2)' }}>
                {issue.risk_level === '高风险'
                  ? '可能导致登记被退回，需立即整改'
                  : issue.risk_level === '中风险'
                  ? '存在合规瑕疵，建议补正后再申报'
                  : '提示性问题，可关注'}
              </span>
            </div>
          </div>

          {/* 3. 规则依据 */}
          <div className="issue-section">
            <div className="label">③ 规则依据</div>
            {allBases.map((b, i) => (
              <div className="content basis" key={i} style={{ marginBottom: 6 }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>
                  <code>{(issue.rule_ids || [issue.rule_id])[i] || issue.rule_id}</code>
                  <span style={{ marginLeft: 8, color: 'var(--c-text-3)', fontWeight: 400 }}>
                    {b?.basis_type === '用户新增' ? '· 用户新增' : '· 内置规则'}
                  </span>
                </div>
                <div style={{ marginBottom: 4 }}>{b?.rule_text}</div>
                {b?.basis_file && (
                  <div style={{ color: 'var(--c-text-3)', fontSize: 11.5 }}>
                    📎 {b.basis_file}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* 4. 问题点位 */}
          <div className="issue-section">
            <div className="label">④ 问题点位</div>
            {locations.length === 0 ? (
              <div className="content">未定位到具体字段</div>
            ) : (
              locations.map((loc, i) => (
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
                </div>
              ))
            )}
          </div>

          {/* 5. AI 整改建议 */}
          <div className="issue-section">
            <div className="label">⑤ AI 整改建议</div>
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
}
