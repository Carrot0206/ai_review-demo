import { useEffect, useState } from 'react'
import {
  FileSearchOutlined,
  FileTextOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons'
import RuleLibraryPage from './pages/RuleLibraryPage'
import ReviewWorkspacePage from './pages/ReviewWorkspacePage'
import './app.css'


type ManagementPage = 'rule-library' | 'review'

function pageFromPath(): ManagementPage {
  return window.location.pathname.includes('/review') ? 'review' : 'rule-library'
}

export default function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [page, setPage] = useState<ManagementPage>(pageFromPath)

  useEffect(() => {
    const handlePopState = () => setPage(pageFromPath())
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  function navigate(event: React.MouseEvent<HTMLAnchorElement>, nextPage: ManagementPage, path: string) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    window.history.pushState({}, '', path)
    setPage(nextPage)
  }

  return (
    <div className={`management-shell${sidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
      <aside className="management-sidebar" aria-label="管理中台主导航">
        <div className="management-sidebar-brand">
          <div className="management-sidebar-logo" aria-hidden="true">信</div>
          <div className="management-sidebar-title">信托登记审查管理中台</div>
        </div>

        <button
          type="button"
          className="management-sidebar-toggle"
          aria-label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
          aria-expanded={!sidebarCollapsed}
          onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
        >
          {sidebarCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </button>

        <nav className="management-sidebar-nav">
          <a
            className={`management-sidebar-link${page === 'rule-library' ? ' active' : ''}`}
            href="/rule-library/"
            aria-current={page === 'rule-library' ? 'page' : undefined}
            title={sidebarCollapsed ? '信托规则库' : undefined}
            onClick={(event) => navigate(event, 'rule-library', '/rule-library/')}
          >
            <FileTextOutlined />
            <span>信托规则库</span>
          </a>
          <a
            className={`management-sidebar-link${page === 'review' ? ' active' : ''}`}
            href="/rule-library/review"
            aria-current={page === 'review' ? 'page' : undefined}
            title={sidebarCollapsed ? '信托产品登记审核' : undefined}
            onClick={(event) => navigate(event, 'review', '/rule-library/review')}
          >
            <FileSearchOutlined />
            <span>信托产品登记审核</span>
          </a>
        </nav>
      </aside>

      <div className="management-content">
        {page === 'rule-library' ? <RuleLibraryPage /> : <ReviewWorkspacePage />}
      </div>
    </div>
  )
}
