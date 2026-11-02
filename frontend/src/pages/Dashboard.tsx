import { Link } from 'react-router-dom'
import {
  ArrowDownLeft,
  ArrowRight,
  ArrowUpRight,
  CreditCard,
  Receipt,
  Send,
  Sparkles,
  TrendingUp,
  Wallet,
} from 'lucide-react'
import { useOverview } from '@/hooks/useOverview'
import { transactionApi } from '@/api'
import { useAsync } from '@/hooks/useAsync'
import { useCurrentAccount } from '@/context/AccountContext'
import {
  Badge,
  ErrorState,
  SectionHeader,
  Skeleton,
  formatCurrency,
  formatDate,
} from '@/components/ui/primitives'
import { CategoryBars, TrendChart } from '@/components/ui/charts'

const CATEGORY_ICONS: Record<string, string> = {
  餐饮美食: '餐饮',
  交通出行: '交通',
  购物消费: '购物',
  生活缴费: '缴费',
  娱乐休闲: '娱乐',
  医疗健康: '医疗',
  教育学习: '教育',
  住房物业: '住房',
  金融理财: '理财',
  转账支出: '转账',
  工资收入: '工资',
}

export default function Dashboard() {
  const { accountId } = useCurrentAccount()
  const { overview, loading, error, reload } = useOverview()
  const stats = useAsync(() => transactionApi.stats(accountId), [accountId])

  if (loading) return <DashboardSkeleton />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!overview) return <ErrorState message="未获取到账户数据" onRetry={reload} />

  const { account, cards, recent_transactions: recent, stats: overviewStats, payees } = overview
  const monthlyTrend = stats.data?.trend ?? overviewStats.trend
  const categories = overviewStats.categories ?? []

  return (
    <div className="space-y-6 max-w-[1400px]">
      {/* ---------------- 顶部：账户总览 ---------------- */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* 主余额卡 */}
        <div className="xl:col-span-2 surface-dark relative overflow-hidden p-6">
          <div className="absolute -right-16 -top-16 w-56 h-56 rounded-full border border-white/[0.07]" />
          <div className="absolute -right-6 -bottom-20 w-44 h-44 rounded-full border border-white/[0.05]" />

          <div className="relative">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[0.6875rem] uppercase tracking-[0.16em] text-navy-300 font-semibold">
                  Total Balance · 账户总余额
                </div>
                <div className="mt-3 flex items-baseline gap-2">
                  <span className="text-[0.9375rem] text-navy-300/90 font-medium">¥</span>
                  <span className="text-[2.25rem] leading-none font-semibold text-white tnum tracking-tight">
                    {account.balance.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[0.75rem] text-navy-200/80">
                  <span>
                    {account.holder_name} · {account.account_type === 'credit' ? '信用账户' : '储蓄账户'}
                  </span>
                  <span className="text-navy-400/60">尾号 {account.account_no.slice(-4)}</span>
                  <span className="inline-flex items-center gap-1 text-emerald-300/90">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    {account.status === 'active' ? '账户正常' : '账户冻结'}
                  </span>
                </div>
              </div>

              <div className="hidden sm:flex flex-col gap-2 shrink-0">
                <Link to="/transfer" className="btn btn-sm btn-gold">
                  <Send className="w-3.5 h-3.5" />
                  发起转账
                </Link>
                <Link to="/agent" className="btn btn-sm bg-white/10 text-white hover:bg-white/15 border border-white/10">
                  <Sparkles className="w-3.5 h-3.5" />
                  AI 助手
                </Link>
              </div>
            </div>

            <div className="mt-6 pt-5 border-t border-white/[0.08] grid grid-cols-2 sm:grid-cols-4 gap-4">
              <Metric label="可用余额" value={formatCurrency(account.available)} />
              <Metric label="周期支出" value={formatCurrency(overviewStats.total_expense)} />
              <Metric label="周期收入" value={formatCurrency(overviewStats.total_income)} accent />
              <Metric label="名下卡片" value={`${account.card_count} 张`} />
            </div>

            {/* 预算进度 + 支出 Top3 */}
            <div className="mt-5 pt-5 border-t border-white/[0.08] grid grid-cols-1 sm:grid-cols-2 gap-6">
              <div>
                <div className="flex items-baseline justify-between mb-2">
                  <span className="text-[0.625rem] uppercase tracking-[0.12em] text-navy-400/70 font-semibold">
                    Monthly Budget · 周期预算
                  </span>
                  <span className="text-[0.6875rem] text-navy-300/80 tnum">
                    ¥{formatCurrency(overviewStats.total_expense).replace('¥', '')} / ¥50,000.00
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-champagne-300 transition-all duration-500"
                    style={{ width: `${Math.min(100, (overviewStats.total_expense / 50000) * 100)}%` }}
                  />
                </div>
                <div className="mt-2 text-[0.625rem] text-navy-400/60">
                  周期支出占预算 {((overviewStats.total_expense / 50000) * 100).toFixed(1)}%
                  {overviewStats.total_expense > 50000 && ' · 已超出预算'}
                </div>
              </div>

              <div>
                <div className="text-[0.625rem] uppercase tracking-[0.12em] text-navy-400/70 font-semibold mb-2">
                  Top Categories · 支出前三
                </div>
                <div className="space-y-1.5">
                  {categories.slice(0, 3).map((c) => (
                    <div key={c.category} className="flex items-center justify-between gap-3">
                      <span className="text-[0.75rem] text-navy-100/90 truncate">{c.category}</span>
                      <span className="text-[0.6875rem] text-navy-300/80 tnum shrink-0">
                        ¥{c.amount.toLocaleString('zh-CN')} · {(c.ratio * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                  {categories.length === 0 && (
                    <div className="text-[0.6875rem] text-navy-400/60">本周期暂无消费</div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 快捷入口 / 常用收款人 */}
        <div className="surface flex flex-col">
          <SectionHeader
            eyebrow="Quick Actions"
            title="常用收款人"
            subtitle="AI 转账时可直接引用"
            action={
              <Link to="/transfer" className="btn btn-sm btn-ghost">
                管理
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            }
          />
          <div className="px-3 pb-3 space-y-0.5 flex-1">
            {payees.slice(0, 6).map((p) => (
              <div
                key={p.id}
                className="flex items-center gap-3 px-2.5 py-2.5 rounded-lg hover:bg-[#f6f7f9] transition-colors"
              >
                <div className="w-8 h-8 rounded-lg bg-navy-100 text-navy-700 grid place-items-center text-[0.75rem] font-semibold shrink-0">
                  {p.name.slice(0, 1)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-[0.8125rem] font-medium text-ink truncate">{p.name}</div>
                  <div className="text-[0.6875rem] text-ink-muted tnum">
                    {p.masked_account_no} · {p.bank_name}
                  </div>
                </div>
                {p.is_frequent ? (
                  <Badge tone="green">常用</Badge>
                ) : (
                  <Badge tone="neutral">{p.total_count} 次</Badge>
                )}
              </div>
            ))}
            {payees.length === 0 && (
              <div className="py-8 text-center text-[0.75rem] text-ink-muted">暂无收款人</div>
            )}
          </div>
        </div>
      </div>

      {/* ---------------- 统计区 ---------------- */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <div className="xl:col-span-2 surface">
          <SectionHeader
            eyebrow="Spending Trend"
            title="近 6 个月收支趋势"
            subtitle="深色为支出，金色为收入"
            action={
              <Link to="/bills" className="btn btn-sm btn-secondary">
                <Receipt className="w-3.5 h-3.5" />
                账单分析
              </Link>
            }
          />
          <div className="px-4 pb-5">
            {stats.loading ? (
              <Skeleton className="h-[180px] w-full" />
            ) : (
              <TrendChart data={monthlyTrend} />
            )}
          </div>
        </div>

        <div className="surface">
          <SectionHeader eyebrow="Categories" title="周期消费分类" subtitle="按支出金额降序" />
          <div className="px-5 pb-5 max-h-[320px] overflow-y-auto scrollbar-thin">
            {categories.length ? (
              <CategoryBars data={categories} />
            ) : (
              <div className="py-8 text-center text-[0.75rem] text-ink-muted">本月暂无消费</div>
            )}
          </div>
        </div>
      </div>

      {/* ---------------- 卡片 + 近期交易 ---------------- */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <div className="surface">
          <SectionHeader
            eyebrow="Cards"
            title="我的银行卡"
            action={
              <Link to="/cards" className="btn btn-sm btn-ghost">
                全部
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            }
          />
          <div className="px-3 pb-3 space-y-2">
            {cards.map((card) => (
              <div key={card.id} className="rounded-xl border border-[#e3e8ef] bg-[#fafbfc] p-3.5">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-navy-900 grid place-items-center shrink-0">
                    <CreditCard className="w-4 h-4 text-champagne-300" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[0.8125rem] font-medium text-ink truncate">{card.card_name}</span>
                      {card.is_virtual && <Badge tone="gold">虚拟卡</Badge>}
                    </div>
                    <div className="text-[0.6875rem] text-ink-muted tnum mt-0.5">{card.masked_card_no}</div>
                  </div>
                  <CardStatus status={card.status} />
                </div>
                <div className="mt-3 flex items-center justify-between text-[0.6875rem] text-ink-muted">
                  <span>单日限额 ¥{card.daily_limit.toLocaleString('zh-CN')}</span>
                  <span>有效期 {card.expire_month}</span>
                </div>
              </div>
            ))}
            {cards.length === 0 && (
              <div className="py-8 text-center text-[0.75rem] text-ink-muted">名下暂无银行卡</div>
            )}
          </div>
        </div>

        <div className="xl:col-span-2 surface">
          <SectionHeader
            eyebrow="Recent Transactions"
            title="近期交易"
            subtitle="全部为模拟流水"
            action={
              <Link to="/bills" className="btn btn-sm btn-secondary">
                查看全部流水
              </Link>
            }
          />
          <div className="overflow-x-auto scrollbar-thin">
            <table className="table-base">
              <thead>
                <tr>
                  <th>交易对象</th>
                  <th>分类</th>
                  <th>时间</th>
                  <th className="text-right">金额</th>
                  <th className="text-right">余额</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((tx) => (
                  <tr key={tx.id}>
                    <td>
                      <div className="flex items-center gap-2.5">
                        <span className="w-7 h-7 rounded-md bg-[#eef1f5] text-ink-soft grid place-items-center text-[0.625rem] font-semibold shrink-0">
                          {CATEGORY_ICONS[tx.category] ?? '其他'}
                        </span>
                        <div className="min-w-0">
                          <div className="text-[0.8125rem] font-medium text-ink truncate max-w-[220px]">
                            {tx.merchant || tx.counterparty || '未知商户'}
                          </div>
                          {tx.is_simulated && (
                            <div className="text-[0.625rem] text-champagne-700">模拟交易</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td>
                      <Badge tone="neutral">{tx.category}</Badge>
                    </td>
                    <td className="text-[0.75rem] text-ink-muted whitespace-nowrap tnum">
                      {formatDate(tx.occurred_at)}
                    </td>
                    <td className="text-right">
                      <span
                        className={`amount text-[0.8125rem] ${
                          tx.direction === 'income' ? 'amount-income' : 'amount-expense'
                        } inline-flex items-center gap-1`}
                      >
                        {tx.direction === 'income' ? (
                          <ArrowDownLeft className="w-3 h-3" />
                        ) : (
                          <ArrowUpRight className="w-3 h-3" />
                        )}
                        {tx.direction === 'income' ? '+' : '-'}
                        {Math.abs(tx.amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                      </span>
                    </td>
                    <td className="text-right text-[0.75rem] text-ink-muted tnum whitespace-nowrap">
                      {tx.balance_after.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {recent.length === 0 && (
              <div className="py-10 text-center text-[0.75rem] text-ink-muted">暂无交易记录</div>
            )}
          </div>
        </div>
      </div>

      {/* ---------------- 能力入口 ---------------- */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <CapabilityCard
          to="/agent"
          icon={Sparkles}
          title="AI 助手工作台"
          en="Agent Workbench"
          desc="自然语言发起转账、查询账单与管理卡片，全程展示 DAG 执行轨迹。"
        />
        <CapabilityCard
          to="/bills"
          icon={TrendingUp}
          title="账单智能分析"
          en="Bill Analytics"
          desc="消费分类、月度统计与异常交易识别，支持自然语言追问。"
        />
        <CapabilityCard
          to="/audit"
          icon={Wallet}
          title="安全审计中心"
          en="Security Audit"
          desc="所有受控操作的权限判定与执行记录，可追溯、可审计。"
        />
      </div>
    </div>
  )
}

function Metric({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <div className="text-[0.625rem] uppercase tracking-[0.12em] text-navy-400/70 font-semibold">{label}</div>
      <div className={`mt-1 text-[0.9375rem] font-semibold tnum ${accent ? 'text-champagne-300' : 'text-white'}`}>
        {value}
      </div>
    </div>
  )
}

function CardStatus({ status }: { status: string }) {
  if (status === 'active') return <Badge tone="green">正常</Badge>
  if (status === 'frozen') return <Badge tone="amber">已冻结</Badge>
  if (status === 'lost') return <Badge tone="rose">已挂失</Badge>
  return <Badge tone="neutral">{status}</Badge>
}

function CapabilityCard({
  to,
  icon: Icon,
  title,
  en,
  desc,
}: {
  to: string
  icon: typeof Sparkles
  title: string
  en: string
  desc: string
}) {
  return (
    <Link
      to={to}
      className="surface p-5 hover:shadow-lifted hover:border-[#cdd6e2] transition-all duration-200 group"
    >
      <div className="w-9 h-9 rounded-lg bg-navy-900 grid place-items-center mb-3.5 group-hover:bg-navy-800 transition-colors">
        <Icon className="w-4 h-4 text-champagne-300" strokeWidth={1.9} />
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-[0.875rem] font-semibold text-ink">{title}</span>
        <span className="text-[0.625rem] uppercase tracking-wider text-ink-muted">{en}</span>
      </div>
      <p className="mt-1.5 text-[0.75rem] leading-relaxed text-ink-muted">{desc}</p>
    </Link>
  )
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6 max-w-[1400px]">
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <div className="xl:col-span-2 surface-dark p-6 space-y-4">
          <Skeleton className="h-3 w-40 bg-white/10" />
          <Skeleton className="h-9 w-56 bg-white/10" />
          <Skeleton className="h-3 w-72 bg-white/10" />
        </div>
        <div className="surface p-5 space-y-3">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <div className="xl:col-span-2 surface p-5">
          <Skeleton className="h-4 w-32 mb-4" />
          <Skeleton className="h-[180px] w-full" />
        </div>
        <div className="surface p-5">
          <Skeleton className="h-4 w-28 mb-4" />
          <Skeleton className="h-32 w-full" />
        </div>
      </div>
    </div>
  )
}
