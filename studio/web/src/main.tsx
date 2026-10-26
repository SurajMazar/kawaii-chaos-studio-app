import '@ant-design/v5-patch-for-react-19'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App as AntApp, ConfigProvider } from 'antd'
import { StyleProvider } from '@ant-design/cssinjs'
import './index.css'
import { appTheme } from './theme'
import App from './App.tsx'
import { AuthGate } from './pages/AuthPages'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* Ant Design's styles go into @layer antd (ordered in index.css), so Tailwind utilities on its components win */}
    <StyleProvider layer>
      <ConfigProvider theme={appTheme}>
        <AntApp className="h-full" message={{ maxCount: 3 }}>
          <AuthGate><App /></AuthGate>
        </AntApp>
      </ConfigProvider>
    </StyleProvider>
  </StrictMode>,
)
