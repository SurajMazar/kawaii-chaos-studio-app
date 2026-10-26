import { createContext, useContext, useState } from 'react'
import { Button, Drawer, Grid, Layout, Menu, Result, Tooltip } from 'antd'
import {
  AppstoreOutlined, CustomerServiceOutlined, PlusCircleOutlined, SettingOutlined, ToolOutlined,
  MenuFoldOutlined, MenuUnfoldOutlined, FileImageOutlined, TeamOutlined, MenuOutlined,
} from '@ant-design/icons'
import { canLeave, go, useRoute } from './router'
import { JobsButton } from './components/Jobs'
import Dashboard from './pages/Dashboard'
import PiecePage from './pages/PiecePage'
import MusicVideos from './pages/MusicVideos'
import LyricEditor from './pages/LyricEditor'
import ReelEditor from './pages/ReelEditor'
import NewProject from './pages/NewProject'
import Tools from './pages/Tools'
import SettingsPage from './pages/Settings'
import UsersPage from './pages/Users'
import { ReadOnlyBanner, UserMenu } from './components/UserMenu'
import { useCan } from './auth'

const { Sider, Header, Content } = Layout

/** Phones / narrow windows: the menu is a slide-out drawer opened from the page header. */
const NavCtx = createContext<{ mobile: boolean; open: () => void }>({ mobile: false, open: () => {} })

export default function App() {
  const { parts } = useRoute()
  const page = parts[0] ?? ''
  const wide = page === 'lyric' || page === 'reel'
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem('kcs.sider') === '1' } catch { return false } })
  const isAdmin = useCan('admin'), isEditor = useCan('editor')
  const screens = Grid.useBreakpoint()
  const mobile = screens.md === false                  // < 768 px
  const [navOpen, setNavOpen] = useState(false)
  const isCollapsed = !mobile && (wide || collapsed)

  const sel = page === '' ? 'home' : page === 'p' ? (parts[1] === 'mv' ? 'music' : 'home') : page === 'lyric' ? 'music' : page === 'reel' ? 'home' : page
  const nav = (path: string) => { if (canLeave()) { go(path); setNavOpen(false) } }
  const items = [
    { key: 'home', icon: <AppstoreOutlined />, label: 'Library', onClick: () => nav('/') },
    { key: 'music', icon: <CustomerServiceOutlined />, label: 'Music videos', onClick: () => nav('/music') },
    ...(isEditor ? [{ key: 'new', icon: <PlusCircleOutlined />, label: 'New project', onClick: () => nav('/new') }] : []),
    ...(isAdmin ? [{ key: 'tools', icon: <ToolOutlined />, label: 'Tools', onClick: () => nav('/tools') }] : []),
    ...(isAdmin ? [{ key: 'users', icon: <TeamOutlined />, label: 'Users', onClick: () => nav('/users') }] : []),
    { key: 'settings', icon: <SettingOutlined />, label: 'Settings', onClick: () => nav('/settings') },
  ]

  let body: React.ReactNode
  if (page === '') body = <Dashboard />
  else if (page === 'p' && parts[2]) body = <PiecePage kind={parts[1] === 'mv' ? 'mv' : 'strip'} id={parts[2]} tab={parts[3]} key={parts[1] + parts[2]} />
  else if (page === 'music') body = <MusicVideos />
  else if (page === 'lyric' && parts[1]) body = <LyricEditor pid={parts[1]} file={parts[2]} key={parts[1] + (parts[2] ?? '')} />
  else if (page === 'reel' && parts[1]) body = <ReelEditor id={parts[1]} key={parts[1]} />
  else if (page === 'new') body = <NewProject />
  else if (page === 'tools') body = <Tools />
  else if (page === 'settings') body = <SettingsPage tab={parts[1]} />
  else if (page === 'users' && isAdmin) body = <UsersPage />
  else body = <Result status="404" title="Page not found" extra={<Button type="primary" onClick={() => go('/')}>Back to the library</Button>} />

  const brand = (
    <div className={`flex items-center gap-2.5 h-[60px] cursor-pointer select-none overflow-hidden ${isCollapsed ? 'justify-center' : 'px-4'}`} onClick={() => nav('/')} data-tour="logo" title="Kawaii Chaos Studio">
      <FileImageOutlined style={{ color: '#ff5d8f', fontSize: 22, flexShrink: 0 }} />
      {!isCollapsed && <div className="min-w-0 leading-none">
        <div className="font-display font-extrabold text-[16px] whitespace-nowrap"><span className="text-pink">Kawaii</span> <span className="text-sun">Chaos</span></div>
        <div className="text-[10.5px] font-semibold tracking-[0.22em] uppercase opacity-60 mt-1">Studio</div>
      </div>}
    </div>
  )
  const menu = <Menu theme="dark" mode="inline" selectedKeys={[sel]} items={items} data-tour="menu" />

  return (
    <NavCtx.Provider value={{ mobile, open: () => setNavOpen(true) }}>
      <Layout className="h-full">
        {mobile ? (
          <Drawer open={navOpen} onClose={() => setNavOpen(false)} placement="left" width={248} closable={false}
            styles={{ body: { padding: 0, display: 'flex', flexDirection: 'column', background: '#141118' } }}>
            {brand}{menu}
            <div className="mt-auto p-2"><UserMenu collapsed={false} /></div>
          </Drawer>
        ) : (
          <Sider collapsed={isCollapsed} width={208} collapsedWidth={64} theme="dark" className="border-r border-[#2f2937]">
            {brand}{menu}
            <div className="absolute bottom-3 left-0 right-0 flex flex-col gap-1 px-2">
              <UserMenu collapsed={isCollapsed} />
              {!wide && <div className="flex justify-center">
                <Tooltip title={collapsed ? 'Show labels' : 'Hide labels'} placement="right">
                  <Button type="text" icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                    onClick={() => { setCollapsed(!collapsed); try { localStorage.setItem('kcs.sider', collapsed ? '0' : '1') } catch { /* private window */ } }} />
                </Tooltip>
              </div>}
            </div>
          </Sider>
        )}
        <Layout className="min-w-0">
          <ReadOnlyBanner />
          <Content className="min-h-0 overflow-hidden flex flex-col">{body}</Content>
        </Layout>
      </Layout>
    </NavCtx.Provider>
  )
}

/** Shared page header: title, subtitle, right-side actions (Jobs button is always there). */
export function PageHeader({ title, sub, extra, back }: { title: React.ReactNode; sub?: React.ReactNode; extra?: React.ReactNode; back?: () => void }) {
  const { mobile, open } = useContext(NavCtx)
  if (mobile) return (                                  // phone: title row, then the actions in a row that scrolls sideways
    <Header className="!h-auto !px-3 !py-2 flex flex-col gap-2 border-b border-[#2f2937] shrink-0 !leading-none">
      <div className="flex items-center gap-2 min-w-0 w-full">
        <Button type="text" icon={<MenuOutlined />} onClick={open} aria-label="Menu" />
        {back && <Button type="text" onClick={back}>←</Button>}
        <div className="min-w-0 flex-1">
          <div className="font-display font-extrabold text-base truncate">{title}</div>
          {sub && <div className="text-[11px] opacity-60 truncate mt-0.5">{sub}</div>}
        </div>
        <JobsButton />
      </div>
      {extra && <div className="flex items-center gap-2 overflow-x-auto w-full pb-0.5 [&>*]:shrink-0">{extra}</div>}
    </Header>
  )
  return (
    <Header className="flex items-center gap-x-3 gap-y-2 flex-wrap !h-auto min-h-[64px] !py-2 border-b border-[#2f2937] shrink-0 !leading-none">
      {back && <Button type="text" onClick={back}>←</Button>}
      <div className="min-w-0 max-w-full">
        <div className="font-display font-extrabold text-lg truncate">{title}</div>
        {sub && <div className="text-xs opacity-60 truncate mt-0.5">{sub}</div>}
      </div>
      <div className="ml-auto flex items-center gap-2 min-w-0 flex-wrap justify-end">{extra}<JobsButton /></div>
    </Header>
  )
}
