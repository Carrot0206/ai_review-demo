import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App as AntdApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import 'antd/dist/reset.css'
import './index.css'
import App from './App'


const theme = {
  token: {
    colorPrimary: '#4A54A8',
    colorInfo: '#4A54A8',
    colorSuccess: '#10B981',
    colorWarning: '#F59E0B',
    colorError: '#DC2626',
    colorBgBase: '#FFFFFF',
    colorBgLayout: '#F0F2F5',
    colorTextBase: '#0F172A',
    borderRadius: 4,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif',
  },
  components: {
    Button: { controlHeight: 34 },
    Card: { borderRadiusLG: 4 },
    Tag: { borderRadiusSM: 4 },
  },
}


createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider locale={zhCN} theme={theme}>
      <AntdApp>
        <App />
      </AntdApp>
    </ConfigProvider>
  </StrictMode>,
)
