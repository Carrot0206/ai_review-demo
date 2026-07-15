import { useEffect } from 'react'
import './App.css'
import Header from './components/Header'
import ProcessBar from './components/ProcessBar'
import LeftPanel from './components/LeftPanel'
import RightPanel from './components/RightPanel'
import { useStore } from './store'
import { getRules, listRuleSets, listUploads } from './api'
import RuleLibraryPage from './pages/RuleLibraryPage'

function ReviewApp() {
  const process = useStore((s) => s.process)
  const setRules = useStore((s) => s.setRules)
  const setRuleSets = useStore((s) => s.setRuleSets)
  const setUploads = useStore((s) => s.setUploads)

  // 切流程刷新当前流程的规则集和上传列表;
  // 审核结果/进度/任务状态按流程隔离保留,不在切流程时清空
  useEffect(() => {
    getRules(process)
      .then((r) => {
        setRules(r)
        setRuleSets(r.rule_sets || [])
      })
      .catch(() => {})
    listRuleSets(process).then(setRuleSets).catch(() => {})
    listUploads(process).then(setUploads).catch(() => {})
  }, [process, setRules, setRuleSets, setUploads])

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

function App() {
  const normalizedPath = window.location.pathname.replace(/\/+$/, '') || '/'
  return normalizedPath === '/rule-library' ? <RuleLibraryPage /> : <ReviewApp />
}

export default App
