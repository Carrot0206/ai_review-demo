import { useEffect } from 'react'
import './App.css'
import Header from './components/Header'
import ProcessBar from './components/ProcessBar'
import LeftPanel from './components/LeftPanel'
import RightPanel from './components/RightPanel'
import { useStore } from './store'
import { getRules, listUploads } from './api'

function App() {
  const process = useStore((s) => s.process)
  const setRules = useStore((s) => s.setRules)
  const setUserRules = useStore((s) => s.setUserRules)
  const setUploads = useStore((s) => s.setUploads)
  const setResult = useStore((s) => s.setResult)
  const setJobId = useStore((s) => s.setJobId)
  const setJobStatus = useStore((s) => s.setJobStatus)
  const setStage = useStore((s) => s.setStage)
  const resetProgress = useStore((s) => s.resetProgress)

  // 切流程刷新规则；切流程也刷新对应流程的上传列表；
  // 同时清空右侧审核结果/进度/任务状态，避免上个流程的结果残留
  useEffect(() => {
    setResult(null)
    setJobId(null)
    setJobStatus('idle')
    setStage('idle')
    resetProgress()

    getRules(process)
      .then((r) => {
        setRules(r)
        setUserRules(r.user_rules || [])
      })
      .catch(() => {})
    listUploads(process).then(setUploads).catch(() => {})
  }, [
    process,
    setRules,
    setUserRules,
    setUploads,
    setResult,
    setJobId,
    setJobStatus,
    setStage,
    resetProgress,
  ])

  return (
    <>
      <Header />
      <ProcessBar />
      <div className="main-grid">
        <div className="left-col">
          <LeftPanel />
        </div>
        <div className="right-col">
          <RightPanel />
        </div>
      </div>
      <div className="app-footer">
        信托登记 AI 辅助审核 Demo · Powered by DeepSeek · 仅用于演示
      </div>
    </>
  )
}

export default App
