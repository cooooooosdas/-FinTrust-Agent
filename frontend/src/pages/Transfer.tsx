import { useEffect, useMemo, useState } from 'react'
import {
  AlertOctagon,
  CheckCircle2,
  KeyRound,
  Loader2,
  Lock,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react'
import { payeeApi, transferApi } from '@/api'
import { ApiError, createIntentIdempotencyKey } from '@/api/client'
import { useCurrentAccount } from '@/context/AccountContext'
import { useAsync } from '@/hooks/useAsync'
import type { Payee, TransferPreview, TransferResult } from '@/types'
import {
  ErrorState,
  RiskBadge,
  SectionHeader,
  SimulationNotice,
} from '@/components/ui/primitives'

type Stage = 'idle' | 'preview' | 'confirmed' | 'mfa' | 'executed' | 'blocked'

export default function Transfer() {
  const { accountId } = useCurrentAccount()
  const payees = useAsync(() => payeeApi.list(accountId), [accountId])
  const policy = useAsync(() => transferApi.policy(), [])
  const daily = useAsync(() => transferApi.dailyTotal(accountId), [accountId])

  const [payeeId, setPayeeId] = useState<number | ''>('')
  const [amount, setAmount] = useState('')
  const [remark, setRemark] = useState('')
  const [stage, setStage] = useState<Stage>('idle')
  const [preview, setPreview] = useState<TransferPreview | null>(null)
  const [result, setResult] = useState<TransferResult | null>(null)
  const [idempotencyKey, setIdempotencyKey] = useState<string>(() => createIntentIdempotencyKey())
  const [mfaCode, setMfaCode] = useState('')
  const [mfaChallengeId, setMfaChallengeId] = useState<string | undefined>()
  const [demoCode, setDemoCode] = useState<string | undefined>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (payees.data && payees.data.length > 0 && payeeId === '') {
      setPayeeId(payees.data[0].id)
    }
  }, [payees.data, payeeId])

  const selectedPayee: Payee | undefined = useMemo(
    () => payees.data?.find((p) => p.id === payeeId),
    [payees.data, payeeId],
  )

  const reset = () => {
    setStage('idle')
    setPreview(null)
    setResult(null)
    setMfaCode('')
    setMfaChallengeId(undefined)
    setDemoCode(undefined)
    setError(null)
    setIdempotencyKey(createIntentIdempotencyKey())
  }

  // ---------------- 预览（后端定级） ----------------
  const handlePreview = async () => {
    setError(null)
    setBusy(true)
    try {
      const p = await transferApi.preview({
        account_id: accountId,
        payee_id: typeof payeeId === 'number' ? payeeId : undefined,
        amount: Number(amount),
        remark: remark.trim(),
      })
      setPreview(p)
      if (p.risk_level === 'red') {
        setStage('mfa')
      } else if (p.risk_level === 'yellow') {
        setStage('confirmed')
      } else {
        setStage('preview')
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '预览失败')
    } finally {
      setBusy(false)
    }
  }

  // ---------------- 执行 ----------------
  const handleExecute = async (opts: { confirm?: boolean; mfa?: boolean } = {}) => {
    if (!preview) return
    setError(null)
    setBusy(true)
    try {
      const res = await transferApi.execute(
        {
          order_no: preview.order_no,
          confirm: opts.confirm ?? true,
          mfa_code: opts.mfa ? mfaCode.trim() : undefined,
          mfa_challenge_id: opts.mfa ? mfaChallengeId : undefined,
        },
        idempotencyKey,
      )
      setResult(res)
      setStage('executed')
      daily.reload()
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
        if (err.code === 'MFA_REQUIRED') {
          setStage('mfa')
          const detail = err.detail as any
          if (detail?.challenge_id) setMfaChallengeId(detail.challenge_id)
          if (detail?.demo_code) setDemoCode(detail.demo_code)
        } else if (err.code === 'CONFIRMATION_REQUIRED') {
          setStage('confirmed')
        }
      } else {
        setError('执行失败')
      }
    } finally {
      setBusy(false)
    }
  }

  const thresholds = policy.data

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] gap-5 max-w-[1400px]">
      {/* ================= 左：操作区 ================= */}
      <div className="space-y-5">
        <div className="surface">
          <SectionHeader
            eyebrow="Transfer"
            title="发起智能转账"
            subtitle="填写收款人与金额，系统将由后端安全策略引擎自动定级"
          />

          <div className="px-5 pb-5 space-y-4">
            {/* 收款人 */}
            <div>
              <label className="field-label" htmlFor="payee">
                收款人
              </label>
              {payees.loading ? (
                <div className="h-10 rounded-lg bg-[#eef1f5]" />
              ) : (
                <select
                  id="payee"
                  className="input"
                  value={payeeId}
                  onChange={(e) => {
                    setPayeeId(e.target.value === '' ? '' : Number(e.target.value))
                    reset()
                  }}
                >
                  {payees.data?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · {p.masked_account_no} · {p.bank_name}
                      {p.is_frequent ? '（常用）' : ''}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* 金额 */}
            <div>
              <label className="field-label" htmlFor="amount">
                转账金额（元）
              </label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted text-[0.875rem]">¥</span>
                <input
                  id="amount"
                  type="number"
                  min="0.01"
                  step="0.01"
                  className="input input-lg pl-8 tnum"
                  placeholder="0.00"
                  value={amount}
                  onChange={(e) => {
                    setAmount(e.target.value)
                    reset()
                  }}
                />
              </div>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {[500, 2000, 10000, 60000].map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => {
                      setAmount(String(v))
                      reset()
                    }}
                    className="px-2.5 h-7 rounded-md text-[0.6875rem] font-medium border border-[#e3e8ef] bg-white text-ink-muted hover:border-navy-300 hover:text-ink transition-colors tnum"
                  >
                    ¥{v.toLocaleString('zh-CN')}
                  </button>
                ))}
              </div>
            </div>

            {/* 备注 */}
            <div>
              <label className="field-label" htmlFor="remark">
                备注（选填）
              </label>
              <input
                id="remark"
                className="input"
                placeholder="例如：项目结算款"
                value={remark}
                onChange={(e) => setRemark(e.target.value)}
                maxLength={100}
              />
            </div>

            {/* 当日累计 */}
            {daily.data && thresholds && (
              <div className="rounded-lg border border-[#e3e8ef] bg-[#fafbfc] px-4 py-3">
                <div className="flex items-center justify-between text-[0.75rem]">
                  <span className="text-ink-muted">当日已转出</span>
                  <span className="font-semibold tnum text-ink">¥{daily.data.daily_total.toLocaleString('zh-CN')}</span>
                </div>
                <div className="mt-2 h-1.5 rounded-full bg-[#e8ecf2] overflow-hidden">
                  <div
                    className="h-full bg-navy-700 transition-all duration-500"
                    style={{
                      width: `${Math.min(100, (daily.data.daily_total / daily.data.red_daily_total) * 100)}%`,
                    }}
                  />
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.6875rem] text-ink-muted">
                  <span>小额上限 ¥{thresholds.yellow_single_max.toLocaleString('zh-CN')}</span>
                  <span>大额阈值 ¥{thresholds.red_single_min.toLocaleString('zh-CN')}</span>
                  <span>日累计红线 ¥{thresholds.red_daily_total.toLocaleString('zh-CN')}</span>
                </div>
              </div>
            )}

            <div className="flex items-center gap-2.5 pt-1">
              <button
                className="btn btn-lg btn-primary flex-1"
                onClick={handlePreview}
                disabled={busy || !amount || !selectedPayee}
              >
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
                提交并评估权限
              </button>
              {(stage !== 'idle' || result) && (
                <button className="btn btn-lg btn-secondary" onClick={reset}>
                  <RefreshCw className="w-4 h-4" />
                  重置
                </button>
              )}
            </div>
          </div>
        </div>

        {/* ---------------- 执行结果 / 确认面板 ---------------- */}
        {(stage === 'confirmed' || stage === 'mfa' || stage === 'executed' || stage === 'preview') && preview && (
          <div className="surface animate-fade-up">
            <SectionHeader
              eyebrow={stage === 'executed' ? 'Executed' : 'Policy Decision'}
              title={stage === 'executed' ? '执行结果' : '权限判定与操作详情'}
              action={<RiskBadge level={preview.risk_level} label={preview.risk.label} />}
            />

            <div className="px-5 pb-5 space-y-4">
              {/* 明细 */}
              <div className="rounded-xl border border-[#e3e8ef] overflow-hidden">
                <DetailRow label="工单号" value={preview.order_no} mono />
                <DetailRow label="收款人" value={`${preview.payee_name}（${preview.masked_payee_account_no}）`} />
                <DetailRow label="转账金额" value={`¥ ${preview.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`} strong />
                <DetailRow label="备注" value={preview.remark || '无'} />
                <DetailRow
                  label="当日累计"
                  value={`¥ ${preview.daily_total_before.toLocaleString('zh-CN')} → ¥ ${preview.daily_total_after.toLocaleString('zh-CN')}`}
                />
                <DetailRow label="剩余额度" value={`¥ ${preview.daily_limit_remaining.toLocaleString('zh-CN')}`} />
              </div>

              {/* 判定依据 */}
              <div className={`rounded-xl border px-4 py-3 ${
                preview.risk_level === 'red'
                  ? 'border-rose-200 bg-rose-50/60'
                  : preview.risk_level === 'yellow'
                    ? 'border-amber-200 bg-amber-50/60'
                    : 'border-emerald-200 bg-emerald-50/60'
              }`}>
                <div className="flex items-start gap-2.5">
                  {preview.risk_level === 'red' ? (
                    <ShieldAlert className="w-4 h-4 text-rose-600 mt-0.5 shrink-0" />
                  ) : preview.risk_level === 'yellow' ? (
                    <AlertOctagon className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
                  ) : (
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 mt-0.5 shrink-0" />
                  )}
                  <div className="min-w-0">
                    <div className="text-[0.8125rem] font-medium text-ink">{preview.risk.reason}</div>
                    <ul className="mt-2 space-y-1">
                      {preview.risk.rules.map((r, i) => (
                        <li key={i} className="text-[0.75rem] text-ink-soft flex gap-2">
                          <span className="text-ink-muted">·</span>
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>

              {/* 错误信息 */}
              {error && (
                <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-[0.8125rem] text-rose-700 flex items-start gap-2">
                  <AlertOctagon className="w-4 h-4 mt-0.5 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* MFA 输入 */}
              {stage === 'mfa' && (
                <div className="rounded-xl border border-navy-200 bg-navy-50 px-4 py-4">
                  <div className="flex items-center gap-2 text-[0.8125rem] font-medium text-navy-900">
                    <KeyRound className="w-4 h-4" />
                    多因子身份验证（模拟）
                  </div>
                  <p className="text-[0.75rem] text-navy-700/80 mt-1.5 leading-relaxed">
                    该操作被判定为高风险，需要完成多因子验证后方可执行。
                    演示环境下验证码由后端直接下发，真实场景应通过短信 / 推送下发。
                  </p>
                  {demoCode && (
                    <div className="mt-3 rounded-lg bg-white border border-navy-200 px-3 py-2.5">
                      <div className="text-[0.6875rem] text-ink-muted">演示验证码</div>
                      <div className="text-[1.25rem] font-semibold tracking-[0.35em] tnum text-navy-900 mt-1">
                        {demoCode}
                      </div>
                    </div>
                  )}
                  <div className="mt-3 flex gap-2">
                    <input
                      className="input tnum tracking-[0.3em] text-center font-mono"
                      placeholder="6 位验证码"
                      maxLength={6}
                      value={mfaCode}
                      onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ''))}
                    />
                    <button
                      className="btn btn-md btn-primary shrink-0"
                      disabled={busy || mfaCode.length !== 6}
                      onClick={() => handleExecute({ confirm: true, mfa: true })}
                    >
                      {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Lock className="w-4 h-4" />}
                      验证并执行
                    </button>
                  </div>
                </div>
              )}

              {/* 确认执行 */}
              {stage === 'confirmed' && (
                <div className="rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-4">
                  <div className="text-[0.8125rem] font-medium text-amber-900">请确认操作明细</div>
                  <p className="text-[0.75rem] text-amber-800/80 mt-1 leading-relaxed">
                    黄色级操作必须由您明确确认后才会真正执行。请核对上方收款人与金额。
                  </p>
                  <button
                    className="btn btn-md btn-primary mt-3"
                    disabled={busy}
                    onClick={() => handleExecute({ confirm: true })}
                  >
                    {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                    我已核对，确认执行
                  </button>
                </div>
              )}

              {/* 绿色：直接执行 */}
              {stage === 'preview' && (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 px-4 py-4">
                  <div className="text-[0.8125rem] font-medium text-emerald-900">绿色操作 · 可直接执行</div>
                  <p className="text-[0.75rem] text-emerald-800/80 mt-1 leading-relaxed">
                    该操作符合常规区间，无需额外验证，执行后会写入审计日志。
                  </p>
                  <button
                    className="btn btn-md btn-success mt-3"
                    disabled={busy}
                    onClick={() => handleExecute({ confirm: true })}
                  >
                    {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                    立即执行
                  </button>
                </div>
              )}

              {/* 执行成功 */}
              {stage === 'executed' && result && (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 px-4 py-4">
                  <div className="flex items-center gap-2 text-[0.875rem] font-semibold text-emerald-800">
                    <CheckCircle2 className="w-4.5 h-4.5" />
                    {result.message}
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-3 text-[0.75rem]">
                    <div>
                      <div className="text-emerald-700/70">交易单号</div>
                      <div className="text-emerald-900 font-mono mt-0.5">{result.transaction_id ?? '—'}</div>
                    </div>
                    <div>
                      <div className="text-emerald-700/70">执行后余额</div>
                      <div className="text-emerald-900 font-semibold tnum mt-0.5">
                        ¥ {result.balance_after.toLocaleString('zh-CN')}
                      </div>
                    </div>
                  </div>
                  <SimulationNotice text={result.simulation_notice} className="mt-3" />
                </div>
              )}
            </div>
          </div>
        )}

        {error && stage === 'idle' && <ErrorState message={error} onRetry={() => setError(null)} title="请求失败" />}
      </div>

      {/* ================= 右：策略说明 ================= */}
      <div className="space-y-5">
        <div className="surface">
          <SectionHeader eyebrow="Policy" title="三级权限策略" subtitle="由后端策略引擎强制执行" />
          <div className="px-5 pb-5 space-y-3">
            {thresholds?.levels.map((lvl) => (
              <div
                key={lvl.level}
                className={`rounded-xl border px-4 py-3 ${
                  lvl.level === 'green'
                    ? 'border-emerald-200 bg-emerald-50/50'
                    : lvl.level === 'yellow'
                      ? 'border-amber-200 bg-amber-50/50'
                      : 'border-rose-200 bg-rose-50/50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <RiskBadge level={lvl.level} label={lvl.label} />
                </div>
                <p className="text-[0.75rem] text-ink-soft mt-2 leading-relaxed">{lvl.reason}</p>
                <ul className="mt-2 space-y-1">
                  {lvl.rules.map((r, i) => (
                    <li key={i} className="text-[0.6875rem] text-ink-muted flex gap-1.5">
                      <span>·</span>
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {policy.loading && <div className="h-40 rounded-xl bg-[#eef1f5]" />}
          </div>
        </div>

        <div className="surface">
          <SectionHeader eyebrow="Guardrails" title="不可绕过的后端护栏" />
          <div className="px-5 pb-5 space-y-2.5">
            <Guardrail
              icon={Lock}
              title="权限判定与模型解耦"
              desc="大模型只输出意图与参数，权限由独立策略引擎依据业务事实判定。"
            />
            <Guardrail
              icon={ShieldCheck}
              title="幂等控制"
              desc="写操作强制携带 Idempotency-Key，重复提交返回首次结果，不会重复扣款。"
            />
            <Guardrail
              icon={KeyRound}
              title="多因子验证"
              desc="红色操作必须通过模拟 MFA 校验，验证码一次性、限时、限次。"
            />
            <Guardrail
              icon={AlertOctagon}
              title="异常熔断"
              desc="模型服务连续失败达阈值即熔断，自动降级到本地规则引擎。"
            />
          </div>
        </div>
      </div>
    </div>
  )
}

function DetailRow({
  label,
  value,
  strong = false,
  mono = false,
}: {
  label: string
  value: string
  strong?: boolean
  mono?: boolean
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-2.5 border-b border-[#eef1f5] last:border-b-0">
      <span className="text-[0.75rem] text-ink-muted shrink-0">{label}</span>
      <span
        className={`text-[0.8125rem] text-right ${
          strong ? 'font-semibold text-ink' : 'text-ink-soft'
        } ${mono ? 'font-mono text-[0.75rem]' : ''} ${label === '转账金额' ? 'tnum' : ''}`}
      >
        {value}
      </span>
    </div>
  )
}

function Guardrail({
  icon: Icon,
  title,
  desc,
}: {
  icon: typeof Lock
  title: string
  desc: string
}) {
  return (
    <div className="flex gap-2.5">
      <div className="w-7 h-7 rounded-lg bg-navy-900 grid place-items-center shrink-0 mt-0.5">
        <Icon className="w-3.5 h-3.5 text-champagne-300" />
      </div>
      <div className="min-w-0">
        <div className="text-[0.8125rem] font-medium text-ink">{title}</div>
        <div className="text-[0.6875rem] text-ink-muted mt-0.5 leading-relaxed">{desc}</div>
      </div>
    </div>
  )
}
