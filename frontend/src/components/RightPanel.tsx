import { useMemo, useRef, useState } from 'react'
import { Button, Collapse, Empty, Popconfirm, Space, Tag, message } from 'antd'
import {
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

type R = '高风险' | '中风险' | '低风险'
const RISK_ORDER: Record<R, number> = { 高风险: 0, 中风险: 1, 低风险: 2 }

export default function RightPanel() {
  const process = useStore((s) => s.process)
  const result = useStore((s) => s.resultByProcess[s.process])
  const jobStatus = useStore((s) => s.jobStatusByProcess[s.process])
  const progress = useStore((s) => s.progressByProcess[s.process])
  const batchProgress = useStore((s) => s.batchProgressByProcess[s.process])
  const clearReviewState = useStore((s) => s.clearReviewState)
  const filterRisks = useStore((s) => s.filterRisks)
  const toggleRisk = useStore((s) => s.toggleRisk)
  const exportRef = useRef<HTMLDivElement>(null)
  const [exporting, setExporting] = useState(false)

  const running = jobStatus === 'pending' || jobStatus === 'running'

  const sortedIssues = useMemo(() => {
    if (!result) return []
    return [...result.issues].sort(
      (a, b) => RISK_ORDER[a.risk_level as R] - RISK_ORDER[b.risk_level as R],
    )
  }, [result])

  const filtered = useMemo(
    () => sortedIssues.filter((i) => filterRisks.has(i.risk_level as R)),
    [sortedIssues, filterRisks],
  )

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

  const { summary, human_review_items, batch_logs } = result

  return (
    <div className="panel" style={{ flex: 1, minHeight: 0 }} ref={exportRef}>
      <div className="panel-header">
        <h3><ThunderboltOutlined style={{ color: 'var(--c-primary)' }} /> AI 审核结果 · {summary.registration_type}</h3>
        <div className="right">
          <Space>
            <Tag color="success">已完成</Tag>
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

      <div className="panel-body" style={{ flex: 1, minHeight: 0 }}>
        {filtered.length === 0 ? (
          <Empty description="未发现命中规则的问题" style={{ padding: 24 }} />
        ) : (
          filtered.map((iss, idx) => (
            <IssueCard key={iss.issue_id} index={idx} issue={iss} defaultOpen={idx < 2} />
          ))
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
                        {b.error && (
                          <span style={{ color: 'var(--c-risk-high)' }}> · {b.error}</span>
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
