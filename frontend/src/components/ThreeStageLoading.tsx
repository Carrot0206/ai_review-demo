import { useStore } from '../store'

const STAGES = [
  { key: 'parse', name: '材料解析', desc: 'PDF/DOCX 抽取文本' },
  { key: 'batch', name: 'AI 分批审核', desc: '按维度并发调用' },
  { key: 'merge', name: '问题去重合并', desc: '同点位多规则聚合' },
] as const

export default function ThreeStageLoading() {
  const stage = useStore((s) => s.stage)
  const order = ['parse', 'batch', 'merge', 'done']
  const cur = order.indexOf(stage as string)

  return (
    <div className="three-stage">
      <div style={{ fontSize: 13, color: 'var(--c-text-2)' }}>
        🤖 正在调用 DeepSeek 审核，请稍候…
      </div>
      <div className="stage-row">
        {STAGES.map((s, i) => {
          const active = i === cur
          const done = i < cur
          return (
            <div
              key={s.key}
              className={`stage-item ${active ? 'active' : ''} ${done ? 'done' : ''}`}
            >
              {active && <span className="pulse" />}
              <div className="icon">{done ? '✓' : i === 0 ? '📄' : i === 1 ? '⚡' : '🧩'}</div>
              <div className="name">{s.name}</div>
              <div className="desc">{s.desc}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
