import { useState } from 'react'
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FileSearch,
  KeyRound,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import { auditApi } from '@/api'
import { useAsync } from '@/hooks/useAsync'
import type { RiskLevel } from '@/types'
import {
  EmptyState,
  ErrorState,
  RiskBadge,
  SectionHeader,
  Skeleton,
  formatDate,
} from '@/components/ui/primitives'

const LEVELS: { key: RiskLevel | 'all'; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'green', label: '绿色' },
  { key: 'yellow', label: '黄色' },
  { key: 'red', label: '红色' },
]

const DECISION_META: Record<string, { label: string; tone: 'green' | 'amber' | 'rose' | 'neutral'; icon: typeof CheckCircle2 }> = {
  allow: { label: '已放行', tone: 'green', icon: CheckCircle2 },
  confirm: { label: '需确认', tone: 'amber', icon: ShieldCheck },
  mfa: { label: '需多因子验证', tone: 'rose', icon: KeyRound },
  block: { label: '已拦截', tone: 'rose', icon: XCircle },
}

const ACTION_LABELS: Record<string, string> = {
  'agent.chat': 'AI 助手对话',
  'transfer.preview': '转账预览',
  'transfer.executed': '转账执行',
  'transfer.mfa_required': '触发多因子验证',
  'transfer.mfa_failed': '多因子验证失败',
  'transfer.insufficient_balance': '余额不足拦截',
  'card.apply_virtual': '申请虚拟卡',
  'card.freeze': '冻结卡片',
  'card.unfreeze': '解冻卡片',
  'card.reported_lost': '银行卡挂失',
  'card.lost_mfa_required': '挂失触发验证',
  'card.lost_mfa_failed': '挂失验证失败',
}

export default function Audit() {
  const [level, setLevel] = useState<RiskLevel | 'all'>('all')
  const [page, setPage] = useState(1)
  const pageSize = 20

  const list = useAsync(
    () => auditApi.list({ risk_level: level === 'all' ? undefined : level, page, page_size: pageSize }),
    [level, page],
  )

  const summary = list.data?.summary
  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1

  return (
    <div className="space-y-5 max-w-[1400px]">
      {/* ---------------- 概览 ---------------- */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <SummaryTile
          label="审计记录总数"
          value={summary?.total ?? 0}
          hint="全部受控操作留痕"
          icon={ScrollText}
        />
        <SummaryTile
          label="绿色 · 自动执行"
          value={summary?.by_risk_level?.green ?? 0}
          hint="低风险查询与常规操作"
          icon={CheckCircle2}
          tone="green"
        />
        <SummaryTile
          label="黄色 · 需确认"
          value={summary?.by_risk_level?.yellow ?? 0}
          hint="用户明确确认后执行"
          icon={ShieldAlert}
          tone="amber"
        />
        <SummaryTile
          label="红色 · 需验证"
          value={summary?.by_risk_level?.red ?? 0}
          hint="多因子验证后方可执行"
          icon={KeyRound}
          tone="rose"
        />
      </div>

      {/* ---------------- 审计完整性验证 ---------------- */}
      <IntegrityPanel />

      {/* ---------------- 日志列表 ---------------- */}
      <div className="surface">
        <SectionHeader
          eyebrow="Audit Trail"
          title="安全审计日志"
          subtitle="所有受安全策略管辖的操作均只追加留痕，不可修改"
          action={
            <div className="flex items-center gap-1 p-1 rounded-lg bg-[#f1f3f7]">
              {LEVELS.map((l) => (
                <button
                  key={l.key}
                  onClick={() => {
                    setLevel(l.key)
                    setPage(1)
                  }}
                  className={`px-3 h-7 rounded-md text-[0.75rem] font-medium transition-all ${
                    level === l.key
                      ? 'bg-white text-ink shadow-sm border border-[#e3e8ef]'
                      : 'text-ink-muted hover:text-ink'
                  }`}
                >
                  {l.label}
                </button>
              ))}
            </div>
          }
        />

        {list.loading ? (
          <div className="px-5 pb-6 space-y-2">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : list.error ? (
          <ErrorState message={list.error} onRetry={list.reload} />
        ) : list.data && list.data.items.length > 0 ? (
          <>
            <div className="overflow-x-auto scrollbar-thin">
              <table className="table-base">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>操作</th>
                    <th>权限等级</th>
                    <th>处置</th>
                    <th>判定说明</th>
                    <th>操作对象</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.items.map((log) => {
                    const meta = DECISION_META[log.decision] ?? DECISION_META.allow
                    const Icon = meta.icon
                    return (
                      <tr key={log.id}>
                        <td className="text-[0.75rem] text-ink-muted tnum whitespace-nowrap">
                          {formatDate(log.created_at)}
                        </td>
                        <td>
                          <div className="text-[0.8125rem] font-medium text-ink">
                            {ACTION_LABELS[log.action] ?? log.action}
                          </div>
                          <div className="text-[0.625rem] text-ink-muted font-mono mt-0.5">{log.action}</div>
                        </td>
                        <td>
                          <RiskBadge level={log.risk_level} />
                        </td>
                        <td>
                          <span
                            className={`badge ${
                              meta.tone === 'green'
                                ? 'badge-green'
                                : meta.tone === 'amber'
                                  ? 'badge-amber'
                                  : meta.tone === 'rose'
                                    ? 'badge-rose'
                                    : 'badge-neutral'
                            }`}
                          >
                            <Icon className="w-3 h-3" />
                            {meta.label}
                          </span>
                        </td>
                        <td className="text-[0.75rem] text-ink-soft max-w-[320px]">{log.reason}</td>
                        <td className="text-[0.75rem] text-ink-muted font-mono whitespace-nowrap">
                          {log.target_type ? `${log.target_type}#${log.target_id}` : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {list.data.total > pageSize && (
              <div className="flex items-center justify-between px-5 py-3 border-t border-[#eef1f5]">
                <span className="text-[0.75rem] text-ink-muted tnum">
                  第 {page} / {totalPages} 页 · 共 {list.data.total} 条
                </span>
                <div className="flex items-center gap-1.5">
                  <button
                    className="btn btn-sm btn-secondary"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    <ChevronLeft className="w-3.5 h-3.5" />
                    上一页
                  </button>
                  <button
                    className="btn btn-sm btn-secondary"
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  >
                    下一页
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          <EmptyState
            title="暂无审计记录"
            hint="发起一次转账或卡片操作后，这里会出现完整的权限判定与执行轨迹。"
            icon={<FileSearch className="w-5 h-5" />}
          />
        )}
      </div>

      {/* ---------------- 安全设计说明 ---------------- */}
      <div className="surface">
        <SectionHeader eyebrow="Design" title="安全设计要点" subtitle="权限判定完全在服务端，模型无法自行决定操作范围" />
        <div className="px-5 pb-5 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          <DesignCard
            title="独立策略引擎"
            desc="policy.py 只接收业务事实（金额、当日累计、是否敏感），不接受模型给出的权限意见，规则命中即定级。"
          />
          <DesignCard
            title="三级权限"
            desc="绿色自动执行；黄色展示明细并要求用户明确确认；红色必须通过模拟多因子身份验证。"
          />
          <DesignCard
            title="幂等与去重"
            desc="写操作强制携带 Idempotency-Key，同键同参返回首次结果、同键异参直接冲突，杜绝重复扣款。"
          />
          <DesignCard
            title="熔断降级"
            desc="模型服务连续失败达阈值即打开熔断，Agent 自动降级到本地规则引擎，核心业务始终可用。"
          />
          <DesignCard
            title="全量审计"
            desc="预览、放行、要求确认、要求验证、被拦截 —— 五种处置全部写入只追加的审计日志。"
          />
          <DesignCard
            title="密钥隔离"
            desc="模型 API Key 仅存在于后端环境变量，既不写入前端代码，也不会出现在任何响应体中。"
          />
        </div>
      </div>
    </div>
  )
}

function SummaryTile({
  label,
  value,
  hint,
  icon: Icon,
  tone = 'navy',
}: {
  label: string
  value: number
  hint: string
  icon: typeof ScrollText
  tone?: 'navy' | 'green' | 'amber' | 'rose'
}) {
  const colorMap = {
    navy: 'text-navy-900',
    green: 'text-emerald-600',
    amber: 'text-amber-600',
    rose: 'text-rose-600',
  }
  return (
    <div className="surface px-5 py-4">
      <div className="flex items-start justify-between">
        <div className="text-[0.6875rem] uppercase tracking-[0.1em] text-ink-muted font-semibold">{label}</div>
        <Icon className={`w-3.5 h-3.5 ${colorMap[tone]}`} />
      </div>
      <div className={`mt-1.5 text-[1.5rem] leading-none font-semibold tnum tracking-tight ${colorMap[tone]}`}>
        {value}
      </div>
      <div className="text-[0.6875rem] text-ink-muted mt-1.5">{hint}</div>
    </div>
  )
}

function DesignCard({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="rounded-xl border border-[#e3e8ef] bg-[#fafbfc] px-4 py-3.5">
      <div className="flex items-center gap-2">
        <ShieldCheck className="w-3.5 h-3.5 text-navy-600" />
        <span className="text-[0.8125rem] font-medium text-ink">{title}</span>
      </div>
      <p className="mt-1.5 text-[0.75rem] text-ink-muted leading-relaxed">{desc}</p>
    </div>
  )
}

function IntegrityPanel() {
  const [result, setResult] = useState<{ status: string; passed: boolean; detail: Record<string, any>; verified_at: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const verify = async () => {
    setLoading(true)
    setError(null)
    try {
      setResult(await auditApi.integrity())
    } catch (err) {
      setError(err instanceof Error ? err.message : '验证失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="surface">
      <SectionHeader
        eyebrow="Integrity"
        title="审计完整性验证"
        subtitle="哈希链 + HMAC 校验，检测审计记录的篡改、删除与重排"
        action={
          <button className="btn btn-sm btn-primary" onClick={verify} disabled={loading}>
            <ShieldCheck className="w-3.5 h-3.5" />
            {loading ? '验证中…' : '立即验证'}
          </button>
        }
      />
      <div className="px-5 pb-5">
        {result ? (
          <div
            className={`rounded-xl border px-4 py-3.5 flex items-start gap-3 ${
              result.passed ? 'border-emerald-200 bg-emerald-50/60' : 'border-rose-200 bg-rose-50/60'
            }`}
          >
            {result.passed ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-600 mt-0.5 shrink-0" />
            ) : (
              <XCircle className="w-5 h-5 text-rose-600 mt-0.5 shrink-0" />
            )}
            <div className="min-w-0 flex-1">
              <div className={`text-[0.875rem] font-semibold ${result.passed ? 'text-emerald-800' : 'text-rose-800'}`}>
                {result.status}
              </div>
              <div className="mt-1 text-[0.75rem] text-ink-soft">
                {result.passed
                  ? `已签名事件 ${result.detail?.total ?? 0} 条，全部校验通过。`
                  : `检测到异常：${JSON.stringify(result.detail)}`}
              </div>
              <div className="mt-1 text-[0.625rem] text-ink-muted">验证时间：{result.verified_at}</div>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-[#e3e8ef] bg-[#fafbfc] px-4 py-3.5">
            <p className="text-[0.75rem] text-ink-muted leading-relaxed">
              点击「立即验证」对审计日志执行哈希链完整性校验。正常时显示 PASS，若记录被篡改、删除或重排则显示 FAILED 并定位异常。
            </p>
          </div>
        )}
        {error && (
          <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-[0.75rem] text-rose-700">
            {error}
          </div>
        )}
      </div>
    </div>
  )
}
