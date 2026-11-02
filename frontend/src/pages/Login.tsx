import { useState } from 'react'
import { Activity, KeyRound, Loader2, Lock, LogIn, ShieldCheck, User as UserIcon } from 'lucide-react'
import { authApi } from '@/api'
import { ApiError, setCurrentUser, setToken } from '@/api/client'

export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState('demo_user_1')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!username || !password) {
      setError('请输入用户名和密码')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const res = await authApi.login(username.trim(), password)
      setToken(res.access_token)
      setCurrentUser({ username: res.user.username, account_ids: res.user.account_ids })
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '登录失败，请检查后端服务')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a1428] px-4">
      <div className="w-full max-w-[400px]">
        {/* 品牌 */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-champagne-300 grid place-items-center shadow-lg">
            <Activity className="w-7 h-7 text-navy-900" strokeWidth={2.4} />
          </div>
          <div className="mt-4 text-[1.375rem] font-semibold text-white tracking-tight">金枢</div>
          <div className="text-[0.6875rem] text-navy-300 font-medium tracking-[0.2em] uppercase mt-1">
            FinTrust Agent
          </div>
          <p className="mt-3 text-[0.75rem] text-navy-300/70 text-center leading-relaxed">
            面向银行业务的可信 AI 智能体系统
          </p>
        </div>

        {/* 登录卡 */}
        <form
          onSubmit={handleSubmit}
          className="bg-white rounded-2xl shadow-2xl p-7 space-y-4"
        >
          <div>
            <label className="field-label" htmlFor="username">
              用户名
            </label>
            <div className="relative mt-1.5">
              <UserIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-muted" />
              <input
                id="username"
                className="input pl-9"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                placeholder="demo_user_1"
              />
            </div>
          </div>

          <div>
            <label className="field-label" htmlFor="password">
              密码
            </label>
            <div className="relative mt-1.5">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-muted" />
              <input
                id="password"
                type="password"
                className="input pl-9"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="请输入密码"
              />
            </div>
          </div>

          {error && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-[0.75rem] text-rose-700 flex items-start gap-2">
              <ShieldCheck className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <button type="submit" className="btn btn-lg btn-primary w-full" disabled={busy}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
            登录
          </button>

          {/* 演示账号说明 */}
          <div className="rounded-lg border border-navy-200 bg-navy-50 px-3.5 py-3">
            <div className="flex items-center gap-1.5 text-[0.75rem] font-medium text-navy-900">
              <KeyRound className="w-3.5 h-3.5" />
              演示账号
            </div>
            <div className="mt-1.5 space-y-0.5 text-[0.6875rem] text-navy-700/80 font-mono">
              <div>demo_user_1 / Demo1234!（账户一）</div>
              <div>demo_user_2 / Demo1234!（账户二）</div>
            </div>
            <p className="mt-1.5 text-[0.625rem] text-navy-600/70 leading-relaxed">
              密码通过环境变量配置，演示模式下仍须登录后方可访问业务数据。
            </p>
          </div>
        </form>

        <p className="mt-6 text-center text-[0.625rem] text-navy-400/60">
          竞赛演示环境 · 不连接任何真实银行账户
        </p>
      </div>
    </div>
  )
}
