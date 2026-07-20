import { forwardRef, useEffect, useState } from 'react'
import { DownOutlined, FileTextOutlined } from '@ant-design/icons'
import type { ReviewIssue } from '../../types'


function riskClass(level: string) {
  if (level === '高风险') return 'high'
  if (level === '中风险') return 'mid'
  return 'low'
}

function methodLabel(issue: ReviewIssue) {
  if (issue.execution_method === 'script') return '脚本'
  if (issue.execution_method === 'ai_fallback') return 'AI兜底'
  return 'AI'
}

interface Props {
  issue: ReviewIssue
  selected?: boolean
  forceOpen?: boolean
  openSignal?: number
  onSelect?: (issue: ReviewIssue) => void
}

const ReviewIssueCard = forwardRef<HTMLElement, Props>(function ReviewIssueCard(
  { issue, selected, forceOpen, openSignal = 0, onSelect },
  ref,
) {
  const [open, setOpen] = useState(false)
  const risk = riskClass(issue.risk_level)
  const bases = issue.rule_bases?.length ? issue.rule_bases : [issue.rule_basis]

  useEffect(() => {
    if (forceOpen) setOpen(true)
  }, [forceOpen, openSignal])

  return (
    <article ref={ref} className={`review-issue-card ${risk}${selected ? ' selected' : ''}`}>
      <button
        type="button"
        className="review-issue-head"
        aria-expanded={open}
        onClick={() => {
          onSelect?.(issue)
          setOpen((value) => !value)
        }}
      >
        <span className="review-issue-title">{issue.issue_summary}</span>
        <span className={`method-tag ${issue.execution_method === 'script' ? 'script' : 'ai'}`}>
          {methodLabel(issue)}
        </span>
        <span className={`risk-tag ${risk}`}>{issue.risk_level}</span>
        <DownOutlined className={`review-issue-chevron${open ? ' open' : ''}`} />
      </button>

      {open && (
        <div className="review-issue-body">
          <section className="review-issue-section">
            <h4>问题点位</h4>
            {issue.issue_location.length === 0 ? (
              <div className="review-issue-content">
                <p>{issue.issue_summary}</p>
                <span className="review-muted">未定位到具体字段</span>
              </div>
            ) : (
              issue.issue_location.map((location, index) => (
                <div className="review-issue-content" key={`${location.location}-${index}`}>
                  <div className="review-location-material">
                    <FileTextOutlined />
                    {location.material_name || '未标明材料'}
                  </div>
                  <div>路径：<code>{location.location || '未定位'}</code></div>
                  <div>取值：<code className="problem-value">{location.value || '空'}</code></div>
                  <div className="review-issue-reason">原因：{issue.issue_summary}</div>
                </div>
              ))
            )}
          </section>

          <section className="review-issue-section">
            <h4>规则依据</h4>
            {bases.map((basis, index) => (
              <div className="review-issue-content basis" key={`${basis.basis_file}-${index}`}>
                {basis.basis_file && <strong>《{basis.basis_file}》</strong>}
                {basis.basis_file && basis.rule_text ? '：' : ''}
                {basis.rule_text || '规则库未提供详细依据文本'}
              </div>
            ))}
          </section>

          <section className="review-issue-section">
            <h4>整改建议</h4>
            <div className="review-issue-content suggestion">
              {issue.suggestion || '请根据规则要求核对并修正。'}
            </div>
          </section>
        </div>
      )}
    </article>
  )
})

export default ReviewIssueCard
