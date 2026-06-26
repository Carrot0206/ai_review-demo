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

  // 切流程刷新规则；初始化加载上传列表
  useEffect(() => {
    getRules(process)
      .then((r) => {
        setRules(r)
        setUserRules(r.user_rules || [])
      })
      .catch(() => {})
  }, [process, setRules, setUserRules])

  useEffect(() => {
    listUploads().then(setUploads).catch(() => {})
  }, [setUploads])

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
