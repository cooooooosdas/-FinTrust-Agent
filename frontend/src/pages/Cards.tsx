import { useState } from 'react'
import {
  AlertOctagon,
  CheckCircle2,
  CreditCard,
  KeyRound,
  Loader2,
  Lock,
  Plus,
  Snowflake,
  Unlock,
  XCircle,
} from 'lucide-react'
import { cardApi } from '@/api'
import { ApiError } from '@/api/client'
import { useCurrentAccount } from '@/context/AccountContext'
import { useAsync } from '@/hooks/useAsync'
import type { BankCard } from '@/types'
import {
  Badge,
  ErrorState,
  SectionHeader,
  SimulationNotice,
} from '@/components/ui/primitives'

const STATUS_META: Record<string, { label: string; tone: 'green' | 'amber' | 'rose' | 'neutral' }> = {
  active: { label: '正常', tone: 'green' },
  frozen: { label: '已冻结', tone: 'amber' },
  lost: { label: '已挂失', tone: 'rose' },
}

export default function Cards() {
  const { accountId } = useCurrentAccount()
  const cards = useAsync(() => cardApi.list(accountId), [accountId])

  const [dialog, setDialog] = useState<null | { type: 'virtual' | 'freeze' | 'lost'; card?: BankCard }>(null)
  const [cardName, setCardName] = useState('')
  const [dailyLimit, setDailyLimit] = useState('5000')
  const [reason, setReason] = useState('')
  const [mfaCode, setMfaCode] = useState('')
  const [mfaChallengeId, setMfaChallengeId] = useState<string | undefined>()
  const [demoCode, setDemoCode] = useState<string | undefined>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const closeDialog = () => {
    setDialog(null)
    setError(null)
    setNotice(null)
    setMfaCode('')
    setMfaChallengeId(undefined)
    setDemoCode(undefined)
    setReason('')
    setCardName('')
  }

  // ---------------- 虚拟卡申请 ----------------
  const handleVirtual = async (confirm = false) => {
    setBusy(true)
    setError(null)
    try {
      const res = await cardApi.applyVirtual(
        {
          card_name: cardName.trim() || '金枢虚拟卡',
          daily_limit: Number(dailyLimit) || 5000,
          expire_month: '2029/12',
        },
        confirm,
      )
      if (res.status === 'awaiting_confirm') {
        setNotice('虚拟卡申请属于黄色权限操作，请确认后提交。')
        return
      }
      setNotice(`虚拟卡 ${res.card?.masked_card_no ?? ''} 已签发（模拟）。`)
      cards.reload()
      closeDialog()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '申请失败')
    } finally {
      setBusy(false)
    }
  }

  // ---------------- 冻结 / 解冻 ----------------
  const handleFreeze = async (card: BankCard, confirm = false) => {
    setBusy(true)
    setError(null)
    try {
      const res = await cardApi.freeze(card.id, confirm)
      if (res.status === 'awaiting_confirm') {
        setNotice('卡片状态变更属于黄色权限操作，请确认后提交。')
        return
      }
      setNotice(`卡片 ${res.masked_card_no} 状态已更新为「${res.card_status}」（模拟）。`)
      cards.reload()
      closeDialog()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败')
    } finally {
      setBusy(false)
    }
  }

  // ---------------- 挂失（红色，需 MFA） ----------------
  const handleLost = async (card: BankCard, withMfa = false) => {
    setBusy(true)
    setError(null)
    try {
      const res = await cardApi.reportLost(
        card.id,
        reason.trim(),
        withMfa ? mfaCode.trim() : undefined,
        withMfa ? mfaChallengeId : undefined,
      )
      if (res.status === 'awaiting_mfa') {
        setDemoCode(res.demo_code)
        setMfaChallengeId(res.challenge_id)
        setNotice('挂失属于红色权限操作，请完成多因子身份验证。')
        return
      }
      setNotice(`卡片 ${res.masked_card_no} 已挂失（模拟操作，不影响任何真实卡片）。`)
      cards.reload()
      closeDialog()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '挂失失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5 max-w-[1400px]">
      <div className="surface">
        <SectionHeader
          eyebrow="Cards"
          title="我的银行卡"
          subtitle="卡片查询、虚拟卡申请与挂失模拟，全部操作由后端策略引擎定级"
          action={
            <button
              className="btn btn-md btn-primary"
              onClick={() => {
                setDialog({ type: 'virtual' })
                setCardName('网购虚拟卡')
                setDailyLimit('5000')
              }}
            >
              <Plus className="w-3.5 h-3.5" />
              申请虚拟卡
            </button>
          }
        />

        {cards.loading ? (
          <div className="px-5 pb-6 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-44 rounded-xl bg-[#eef1f5]" />
            ))}
          </div>
        ) : cards.error ? (
          <ErrorState message={cards.error} onRetry={cards.reload} />
        ) : (
          <div className="px-5 pb-6 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {cards.data?.map((card) => (
              <CardPanel
                key={card.id}
                card={card}
                onFreeze={() => setDialog({ type: 'freeze', card })}
                onLost={() => setDialog({ type: 'lost', card })}
              />
            ))}
            {cards.data?.length === 0 && (
              <div className="col-span-full py-10 text-center text-[0.8125rem] text-ink-muted">
                当前账户下还没有银行卡
              </div>
            )}
          </div>
        )}
      </div>

      <SimulationNotice text="本页所有卡片均为本地模拟数据，虚拟卡不具备真实支付能力，挂失操作不会影响任何真实银行卡。" />

      {/* ================= 操作弹窗 ================= */}
      {dialog && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-navy-950/45 p-4">
          <div className="w-full max-w-md surface shadow-lifted animate-fade-up">
            <div className="px-5 py-4 border-b border-[#e3e8ef] flex items-center gap-2.5">
              {dialog.type === 'virtual' ? (
                <Plus className="w-4 h-4 text-navy-700" />
              ) : dialog.type === 'freeze' ? (
                <Snowflake className="w-4 h-4 text-navy-700" />
              ) : (
                <XCircle className="w-4 h-4 text-rose-600" />
              )}
              <h3 className="text-[0.9375rem] font-semibold text-ink">
                {dialog.type === 'virtual' ? '申请虚拟卡' : dialog.type === 'freeze' ? '卡片状态变更' : '银行卡挂失'}
              </h3>
              <button className="ml-auto btn btn-sm btn-ghost px-2" onClick={closeDialog}>
                取消
              </button>
            </div>

            <div className="px-5 py-4 space-y-4">
              {/* 虚拟卡 */}
              {dialog.type === 'virtual' && (
                <>
                  <div>
                    <label className="field-label" htmlFor="vc-name">
                      卡片名称
                    </label>
                    <input
                      id="vc-name"
                      className="input"
                      value={cardName}
                      onChange={(e) => setCardName(e.target.value)}
                      maxLength={32}
                    />
                  </div>
                  <div>
                    <label className="field-label" htmlFor="vc-limit">
                      单日限额（元）
                    </label>
                    <input
                      id="vc-limit"
                      type="number"
                      className="input tnum"
                      value={dailyLimit}
                      onChange={(e) => setDailyLimit(e.target.value)}
                      min={100}
                      max={100000}
                    />
                  </div>
                  <div className="rounded-lg border border-amber-200 bg-amber-50/70 px-3.5 py-2.5 text-[0.75rem] text-amber-800">
                    虚拟卡申请属于<strong>黄色权限</strong>操作，需您明确确认后才会签发。
                  </div>
                </>
              )}

              {/* 冻结 */}
              {dialog.type === 'freeze' && dialog.card && (
                <>
                  <div className="rounded-lg border border-[#e3e8ef] bg-[#fafbfc] px-3.5 py-3 text-[0.8125rem] space-y-1.5">
                    <div className="flex justify-between">
                      <span className="text-ink-muted">目标卡片</span>
                      <span className="font-mono text-ink">{dialog.card.masked_card_no}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-ink-muted">当前状态</span>
                      <span className="text-ink">{dialog.card.status}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-ink-muted">将变更为</span>
                      <span className="text-ink font-medium">
                        {dialog.card.status === 'frozen' ? 'active（解冻）' : 'frozen（冻结）'}
                      </span>
                    </div>
                  </div>
                  <div className="rounded-lg border border-amber-200 bg-amber-50/70 px-3.5 py-2.5 text-[0.75rem] text-amber-800">
                    卡片状态变更属于<strong>黄色权限</strong>操作，需您明确确认。
                  </div>
                </>
              )}

              {/* 挂失 */}
              {dialog.type === 'lost' && dialog.card && (
                <>
                  <div className="rounded-lg border border-[#e3e8ef] bg-[#fafbfc] px-3.5 py-3 text-[0.8125rem] space-y-1.5">
                    <div className="flex justify-between">
                      <span className="text-ink-muted">目标卡片</span>
                      <span className="font-mono text-ink">{dialog.card.masked_card_no}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-ink-muted">当前状态</span>
                      <span className="text-ink">{dialog.card.status}</span>
                    </div>
                  </div>
                  <div>
                    <label className="field-label" htmlFor="lost-reason">
                      挂失原因
                    </label>
                    <input
                      id="lost-reason"
                      className="input"
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder="例如：钱包遗失"
                      maxLength={200}
                    />
                  </div>
                  <div className="rounded-lg border border-rose-200 bg-rose-50/70 px-3.5 py-2.5 text-[0.75rem] text-rose-800">
                    挂失属于<strong>红色权限</strong>敏感操作，必须通过多因子身份验证。
                  </div>
                  {demoCode && (
                    <div className="rounded-lg bg-white border border-navy-200 px-3.5 py-2.5">
                      <div className="text-[0.6875rem] text-ink-muted">演示验证码</div>
                      <div className="text-[1.125rem] font-semibold tracking-[0.35em] tnum text-navy-900 mt-1">
                        {demoCode}
                      </div>
                    </div>
                  )}
                  {demoCode && (
                    <input
                      className="input tnum tracking-[0.3em] text-center font-mono"
                      placeholder="6 位验证码"
                      maxLength={6}
                      value={mfaCode}
                      onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ''))}
                    />
                  )}
                </>
              )}

              {/* 提示 */}
              {notice && (
                <div className="rounded-lg border border-navy-200 bg-navy-50 px-3.5 py-2.5 text-[0.75rem] text-navy-800 flex items-start gap-2">
                  <KeyRound className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  <span>{notice}</span>
                </div>
              )}
              {error && (
                <div className="rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-[0.75rem] text-rose-700 flex items-start gap-2">
                  <AlertOctagon className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  <span>{error}</span>
                </div>
              )}
            </div>

            <div className="px-5 py-4 border-t border-[#e3e8ef] flex justify-end gap-2">
              <button className="btn btn-md btn-secondary" onClick={closeDialog}>
                取消
              </button>
              {dialog.type === 'virtual' && (
                <button className="btn btn-md btn-primary" disabled={busy} onClick={() => handleVirtual(true)}>
                  {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                  确认申请
                </button>
              )}
              {dialog.type === 'freeze' && dialog.card && (
                <button
                  className="btn btn-md btn-primary"
                  disabled={busy}
                  onClick={() => handleFreeze(dialog.card!, true)}
                >
                  {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                  确认变更
                </button>
              )}
              {dialog.type === 'lost' && dialog.card && (
                <button
                  className="btn btn-md btn-danger"
                  disabled={busy || (!!demoCode && mfaCode.length !== 6)}
                  onClick={() => handleLost(dialog.card!, !!demoCode)}
                >
                  {busy ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : demoCode ? (
                    <Lock className="w-3.5 h-3.5" />
                  ) : (
                    <KeyRound className="w-3.5 h-3.5" />
                  )}
                  {demoCode ? '验证并挂失' : '发起挂失'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function CardPanel({
  card,
  onFreeze,
  onLost,
}: {
  card: BankCard
  onFreeze: () => void
  onLost: () => void
}) {
  const meta = STATUS_META[card.status] ?? STATUS_META.active
  const isVirtual = card.is_virtual

  return (
    <div
      className={`rounded-xl p-5 flex flex-col justify-between min-h-[188px] ${
        isVirtual ? 'bg-navy-900 text-white' : 'bg-[#fafbfc] border border-[#e3e8ef]'
      }`}
    >
      <div>
        <div className="flex items-start justify-between">
          <div className={`w-9 h-9 rounded-lg grid place-items-center ${isVirtual ? 'bg-white/10' : 'bg-navy-900'}`}>
            <CreditCard className={`w-4 h-4 ${isVirtual ? 'text-champagne-300' : 'text-champagne-300'}`} />
          </div>
          <Badge tone={meta.tone}>{meta.label}</Badge>
        </div>

        <div className={`mt-4 text-[0.9375rem] font-semibold tracking-[0.08em] font-mono ${
          isVirtual ? 'text-white' : 'text-ink'
        }`}>
          {card.masked_card_no}
        </div>
        <div className={`text-[0.6875rem] mt-1 ${isVirtual ? 'text-navy-300' : 'text-ink-muted'}`}>
          {card.card_name} · {card.network}
        </div>
      </div>

      <div className={`mt-4 pt-3.5 border-t text-[0.6875rem] flex items-center justify-between ${
        isVirtual ? 'border-white/10 text-navy-300' : 'border-[#e3e8ef] text-ink-muted'
      }`}>
        <span className="tnum">单日 ¥{card.daily_limit.toLocaleString('zh-CN')}</span>
        <span className="tnum">{card.expire_month}</span>
      </div>

      <div className="mt-3 flex gap-2">
        <button
          className={`btn btn-sm flex-1 ${isVirtual ? 'bg-white/10 text-white hover:bg-white/15 border border-white/10' : 'btn-secondary'}`}
          onClick={onFreeze}
          disabled={card.status === 'lost'}
        >
          {card.status === 'frozen' ? (
            <>
              <Unlock className="w-3.5 h-3.5" />
              解冻
            </>
          ) : (
            <>
              <Snowflake className="w-3.5 h-3.5" />
              冻结
            </>
          )}
        </button>
        <button
          className={`btn btn-sm flex-1 ${
            isVirtual
              ? 'bg-white/10 text-white hover:bg-white/15 border border-white/10'
              : 'border border-rose-200 text-rose-600 hover:bg-rose-50'
          }`}
          onClick={onLost}
          disabled={card.status === 'lost'}
        >
          <XCircle className="w-3.5 h-3.5" />
          挂失
        </button>
      </div>
    </div>
  )
}
