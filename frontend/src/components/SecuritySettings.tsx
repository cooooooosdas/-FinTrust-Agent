import { useState } from 'react'
import { AlertTriangle, CheckCircle2, KeyRound, Loader2, Lock, ShieldCheck, X } from 'lucide-react'
import { authApi } from '@/api'
import { ApiError } from '@/api/client'

interface Props {
  onClose: () => void
  onLoggedOut: () => void
}

export default function SecuritySettings({ onClose, onLoggedOut }: Props) {
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [mfaCode, setMfaCode] = useState('')
  const [challengeId, setChallengeId] = useState<string | undefined>()
  const [demoCode, setDemoCode] = useState<string | undefined>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const requestChallenge = async () => {
    if (!oldPassword || !newPassword || !confirmPassword) {
      setError('请填写原密码和新密码')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const res = await authApi.changePasswordChallenge()
      setChallengeId(res.challenge_id)
      setDemoCode(res.demo_code)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '申请验证失败')
    } finally {
      setBusy(false)
    }
  }

  const submit = async () => {
    if (!challengeId || !mfaCode) {
      setError('请先获取并填写验证码')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await authApi.changePassword({
        old_password: oldPassword,
        new_password: newPassword,
        mfa_code: mfaCode,
        mfa_challenge_id: challengeId,
      })
      setDone(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '修改失败')
    } finally {
      setBusy(false)
    }
  }

  const handleDone = () => {
    onLoggedOut()
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/50 px-4">
      <div className="w-full max-w-[440px] bg-white rounded-2xl shadow-2xl">
        {/* 头 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#e3e8ef]">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-navy-900 grid place-items-center">
              <ShieldCheck className="w-4 h-4 text-champagne-300" />
            </div>
            <div>
              <div className="text-[0.875rem] font-semibold text-ink">安全设置</div>
              <div className="text-[0.6875rem] text-ink-muted">修改登录密码</div>
            </div>
          </div>
          <button className="btn btn-sm btn-ghost px-2" onClick={onClose} aria-label="关闭">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 内容 */}
        {done ? (
          <div className="px-6 py-8 text-center space-y-3">
            <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto" />
            <div className="text-[0.875rem] font-medium text-ink">密码修改成功</div>
            <p className="text-[0.75rem] text-ink-soft leading-relaxed">
              旧会话已全部失效，请使用新密码重新登录。
            </p>
            <button className="btn btn-md btn-primary mt-2" onClick={handleDone}>
              重新登录
            </button>
          </div>
        ) : (
          <div className="px-6 py-5 space-y-3.5">
            <div>
              <label className="field-label" htmlFor="oldPwd">原密码</label>
              <input
                id="oldPwd"
                type="password"
                className="input mt-1.5"
                value={oldPassword}
                onChange={(e) => setOldPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="field-label" htmlFor="newPwd">新密码</label>
                <input
                  id="newPwd"
                  type="password"
                  className="input mt-1.5"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  autoComplete="new-password"
                  placeholder="至少 8 位含字母数字"
                />
              </div>
              <div>
                <label className="field-label" htmlFor="confirmPwd">确认新密码</label>
                <input
                  id="confirmPwd"
                  type="password"
                  className="input mt-1.5"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
            </div>

            {/* MFA */}
            <div className="rounded-xl border border-navy-200 bg-navy-50 px-4 py-3">
              <div className="flex items-center gap-2 text-[0.8125rem] font-medium text-navy-900">
                <KeyRound className="w-4 h-4" />
                多因子验证（模拟）
              </div>
              <p className="text-[0.6875rem] text-navy-700/80 mt-1 leading-relaxed">
                密码修改为高风险操作，需完成 MFA 验证。演示环境下验证码由后端直接下发。
              </p>
              {!challengeId ? (
                <button className="btn btn-sm btn-secondary mt-2.5" onClick={requestChallenge} disabled={busy}>
                  {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Lock className="w-3.5 h-3.5" />}
                  获取验证码
                </button>
              ) : (
                <div className="mt-2.5 space-y-2">
                  {demoCode && (
                    <div className="rounded-lg bg-white border border-navy-200 px-3 py-2">
                      <div className="text-[0.625rem] text-ink-muted">演示验证码</div>
                      <div className="text-[1.125rem] font-semibold tracking-[0.3em] tnum text-navy-900">
                        {demoCode}
                      </div>
                    </div>
                  )}
                  <input
                    className="input tnum tracking-[0.3em] text-center font-mono"
                    placeholder="6 位验证码"
                    maxLength={6}
                    value={mfaCode}
                    onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ''))}
                  />
                </div>
              )}
            </div>

            {error && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-[0.75rem] text-rose-700 flex items-start gap-2">
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button className="btn btn-md btn-primary w-full" onClick={submit} disabled={busy || !challengeId || mfaCode.length !== 6}>
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
              确认修改密码
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
