import { useStore } from '../store'

export default function ProcessBar() {
  const process = useStore((s) => s.process)
  const setProcess = useStore((s) => s.setProcess)

  return (
    <div className="process-bar">
      <span className="label">登记流程：</span>
      <span
        className={`process-pill ${process === 'pre_registration' ? 'active' : ''}`}
        onClick={() => setProcess('pre_registration')}
      >
        📄 预登记
      </span>
      <span
        className={`process-pill ${process === 'pre_registration_reapply' ? 'active' : ''}`}
        onClick={() => setProcess('pre_registration_reapply')}
      >
        📝 重新申请预登记
      </span>
      <span
        className={`process-pill ${process === 'pre_report' ? 'active' : ''}`}
        onClick={() => setProcess('pre_report')}
      >
        📋 事前报告
      </span>
      <span
        className={`process-pill ${process === 'initial' ? 'active' : ''}`}
        onClick={() => setProcess('initial')}
      >
        📑 初始登记
      </span>
      <span
        className={`process-pill ${process === 'termination' ? 'active' : ''}`}
        onClick={() => setProcess('termination')}
      >
        🧾 终止登记
      </span>
      <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--c-text-3)' }}>
        切换流程将重新加载对应规则集
      </span>
    </div>
  )
}
