import '@ant-design/v5-patch-for-react-19'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App as AntApp, ConfigProvider } from 'antd'
import './index.css'
import { appTheme } from './theme'
import App from './App.tsx'
import { AuthGate } from './pages/AuthPages'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider theme={appTheme}>
      <AntApp className="h-full" message={{ maxCount: 3 }}>
        <AuthGate><App /></AuthGate>
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
)
