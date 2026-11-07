import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Activity,
  Bot,
  ChevronDown,
  CreditCard,
  LayoutDashboard,
  LogOut,
  Menu,
  Receipt,
  Send,
  ShieldCheck,
  X,
} from 'lucide-react'
import { agentApi, systemApi } from '@/api'
import { getCurrentUser } from '@/api/client'
import { useCurrentAccount } from '@/context/AccountContext'
import SecuritySettings from '@/components/SecuritySettings'
import type { AgentCapabilities, HealthResponse } from '@/types'
import { SimulationNotice } from '@/components/ui/primitives'

const NAV_ITEMS = [
  { to: '/', label: '账户总览', en: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/agent', label: 'AI 工作台', en: 'Agent', icon: Bot, end: false },
  { to: '/bills', label: '账单分析', en: 'Analytics', icon: Receipt, end: false },
  { to: '/transfer', label: '智能转账', en: 'Transfer', icon: Send, end: false },
  { to: '/cards', label: '银行卡管理', en: 'Cards', icon: CreditCard, end: false },
  { to: '/audit', label: '安全审计', en: 'Audit', icon: ShieldCheck, end: false },
]

export default function AppShell({ onLogout }: { onLogout: () => void }) {
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [caps, setCaps] = useState<AgentCapabilities | null>(null)
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [securityOpen, setSecurityOpen] = useState(false)
  const { accountId, accountIds, username, setAccountId } = useCurrentAccount()
  const user = getCurrentUser()

  useEffect(() => {
    systemApi.health().then(setHealth).catch(() => setHealth(null))
    agentApi.capabilities().then(setCaps).catch(() => setCaps(null))
  }, [])

  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  const demoMode = health?.demo_mode ?? true

  return (
    <div className="min-h-screen flex bg-[#f6f7f9]">
      {/* ------------------------------- 侧边栏 ------------------------------- */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-[248px] bg-navy-900 flex flex-col transition-transform duration-200 lg:translate-x-0 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* 品牌区 */}
        <div className="px-5 pt-6 pb-5 border-b border-white/[0.08]">
          <div className="flex items-center gap-3">
            <div className="relative w-9 h-9 rounded-lg bg-champagne-300 grid place-items-center shrink-0">
              <Activity className="w-[18px] h-[18px] text-navy-900" strokeWidth={2.4} />
            </div>
            <div className="min-w-0">
              <div className="text-[0.9375rem] font-semibold text-white tracking-tight leading-tight">金枢</div>
              <div className="text-[0.625rem] text-navy-300 font-medium tracking-[0.12em] uppercase">FinTrust Agent</div>
            </div>
          </div>
          <p className="mt-3 text-[0.6875rem] text-navy-300/80 leading-relaxed">
            面向银行业务的可信 AI 智能体系统
            <br />
            <span className="text-navy-400/70">Trusted AI Agent for Banking</span>
          </p>
        </div>

        {/* 导航 */}
        <nav className="flex-1 px-3 py-4 overflow-y-auto scrollbar-thin">
          <div className="px-3 mb-2 text-[0.625rem] font-semibold uppercase tracking-[0.16em] text-navy-400/70">
            业务模块
          </div>
          <div className="space-y-0.5">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => `nav-item ${isActive ? 'nav-item-active' : ''}`}
                >
                  <Icon className="w-[15px] h-[15px] shrink-0" strokeWidth={1.9} />
                  <span className="flex-1 truncate">{item.label}</span>
                  <span className="text-[0.5625rem] uppercase tracking-wider text-navy-400/50">{item.en}</span>
                </NavLink>
              )
            })}
          </div>
        </nav>

        {/* 底部状态 */}
        <div className="px-4 py-4 border-t border-white/[0.08] space-y-2.5">
          <div className="flex items-center gap-2">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                health?.status === 'ok' ? 'bg-emerald-400' : health ? 'bg-rose-400' : 'bg-amber-400'
              }`}
            />
            <span className="text-[0.6875rem] text-navy-200/80">
              {health?.status === 'ok' ? '后端服务已连接' : health ? '后端服务异常' : '正在连接后端…'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`w-1.5 h-1.5 rounded-full ${demoMode ? 'bg-champagne-300' : 'bg-emerald-400'}`} />
            <span className="text-[0.6875rem] text-navy-200/80">
              {demoMode ? '本地演示模式' : `已接入 ${caps?.llm_model ?? '模型服务'}`}
            </span>
          </div>
          <p className="text-[0.625rem] text-navy-400/60 leading-relaxed pt-1">
            竞赛演示环境 · 所有资金变动均为本地模拟
            <br />
            不连接任何真实银行账户
          </p>
        </div>
      </aside>

      {/* 移动端遮罩 */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-navy-950/50 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* ------------------------------- 主区域 ------------------------------- */}
      <div className="flex-1 lg:pl-[248px] min-w-0 flex flex-col">
        {/* 顶栏 */}
        <header className="sticky top-0 z-20 bg-[#f6f7f9]/88 backdrop-blur-md border-b border-[#e3e8ef]">
          <div className="flex items-center gap-3 h-14 px-4 lg:px-7">
            <button
              className="btn btn-sm btn-ghost lg:hidden px-2"
              onClick={() => setMobileOpen((v) => !v)}
              aria-label="切换菜单"
            >
              {mobileOpen ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
            </button>

            <Breadcrumb />

            <div className="ml-auto flex items-center gap-2">
              {user && (
                <span className="hidden sm:inline-flex items-center gap-1.5 rounded-md bg-navy-50 px-2.5 py-1 text-[0.6875rem] font-medium text-navy-800">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  {username}
                </span>
              )}
              {/* 账户切换 */}
              {accountIds.length > 1 && (
                <div className="relative">
                  <button
                    className="btn btn-sm btn-ghost px-2 gap-1.5"
                    onClick={() => setAccountMenuOpen((v) => !v)}
                    title="切换账户"
                  >
                    <CreditCard className="w-4 h-4" />
                    <span className="text-[0.6875rem] font-medium">账户 {accountId}</span>
                    <ChevronDown className="w-3.5 h-3.5" />
                  </button>
                  {accountMenuOpen && (
                    <div className="absolute right-0 top-full mt-1 w-44 rounded-lg border border-[#e3e8ef] bg-white shadow-lg z-50 py-1">
                      {accountIds.map((id) => (
                        <button
                          key={id}
                          className={`w-full text-left px-3 py-2 text-[0.75rem] flex items-center gap-2 hover:bg-navy-50 ${
                            id === accountId ? 'text-navy-900 font-medium' : 'text-ink-soft'
                          }`}
                          onClick={() => {
                            setAccountId(id)
                            setAccountMenuOpen(false)
                          }}
                        >
                          <span className={`w-1.5 h-1.5 rounded-full ${id === accountId ? 'bg-emerald-500' : 'bg-transparent'}`} />
                          账户 {id}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {demoMode && (
                <span className="hidden sm:inline-flex items-center gap-1.5 rounded-md bg-champagne-100 px-2.5 py-1 text-[0.6875rem] font-medium text-champagne-800">
                  <span className="w-1.5 h-1.5 rounded-full bg-champagne-500" />
                  模拟交易 · 本地演示
                </span>
              )}
              <span className="hidden md:inline text-[0.6875rem] text-ink-muted font-mono">
                v{health?.version ?? '1.0.0'}
              </span>
              <button
                className="btn btn-sm btn-ghost px-2 gap-1.5"
                onClick={() => setSecurityOpen(true)}
                title="安全设置"
                aria-label="安全设置"
              >
                <ShieldCheck className="w-4 h-4" />
              </button>
              <button
                className="btn btn-sm btn-ghost px-2 gap-1.5"
                onClick={onLogout}
                title="退出登录"
                aria-label="退出登录"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          </div>
        </header>

        {/* 页面内容 */}
        <main className="flex-1 px-4 lg:px-7 py-6 pb-12">
          {demoMode && health && (
            <SimulationNotice text={health.demo_mode_notice} className="mb-5 max-w-4xl" />
          )}
          <Outlet />
        </main>
      </div>

      {/* 安全设置（密码修改） */}
      {securityOpen && (
        <SecuritySettings onClose={() => setSecurityOpen(false)} onLoggedOut={onLogout} />
      )}
    </div>
  )
}

function Breadcrumb() {
  const location = useLocation()
  const current = NAV_ITEMS.find((item) =>
    item.end ? location.pathname === item.to : location.pathname.startsWith(item.to),
  )
  return (
    <div className="flex items-baseline gap-2 min-w-0">
      <span className="text-[0.8125rem] font-medium text-ink truncate">{current?.label ?? '金枢'}</span>
      <span className="text-[0.6875rem] text-ink-muted hidden sm:inline">{current?.en ?? ''}</span>
    </div>
  )
}
