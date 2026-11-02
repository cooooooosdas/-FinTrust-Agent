import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowDownLeft,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Download,
  Filter,
  Search,
} from 'lucide-react'
import { transactionApi } from '@/api'
import { useAsync } from '@/hooks/useAsync'
import { useCurrentAccount } from '@/context/AccountContext'
import {
  Badge,
  EmptyState,
  ErrorState,
  LoadingState,
  SectionHeader,
  Skeleton,
  formatCurrency,
  formatDate,
  formatMonth,
} from '@/components/ui/primitives'
import { CategoryBars, DonutChart, TrendChart } from '@/components/ui/charts'

const PERIODS = [
  { key: 'last_30d', label: '近 30 天' },
  { key: 'current_month', label: '本月' },
  { key: 'last_month', label: '上月' },
  { key: 'last_90d', label: '近 90 天' },
  { key: 'last_180d', label: '近 180 天' },
]

const CATEGORIES = [
  '全部',
  '餐饮美食',
  '交通出行',
  '购物消费',
  '生活缴费',
  '娱乐休闲',
  '医疗健康',
  '教育学习',
  '住房物业',
  '金融理财',
  '转账支出',
  '工资收入',
]

export default function BillAnalysis() {
  const { accountId } = useCurrentAccount()
  const [period, setPeriod] = useState('last_30d')
  const [category, setCategory] = useState('全部')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 15

  const periodStats = useAsync(() => transactionApi.stats(accountId, period), [accountId, period])

  const listQuery = useMemo(
    () => ({
      account_id: accountId,
      category: category === '全部' ? undefined : category,
      keyword: keyword.trim() || undefined,
      page,
      page_size: pageSize,
    }),
    [accountId, category, keyword, page],
  )
  const list = useAsync(() => transactionApi.list(listQuery), [listQuery])

  const activeStats = periodStats.data
  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1

  return (
    <div className="space-y-5 max-w-[1400px]">
      {/* ---------------- 周期选择 ---------------- */}
      <div className="surface px-5 py-4 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1 p-1 rounded-lg bg-[#f1f3f7]">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              onClick={() => {
                setPeriod(p.key)
                setPage(1)
              }}
              className={`px-3 h-7 rounded-md text-[0.75rem] font-medium transition-all ${
                period === p.key
                  ? 'bg-white text-ink shadow-sm border border-[#e3e8ef]'
                  : 'text-ink-muted hover:text-ink'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-muted" />
          <input
            className="input pl-8 w-56"
            placeholder="搜索商户 / 备注"
            value={keyword}
            onChange={(e) => {
              setKeyword(e.target.value)
              setPage(1)
            }}
          />
        </div>
      </div>

      {/* ---------------- 指标卡 ---------------- */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricTile
          label={activeStats ? formatPeriodLabel(activeStats.month) : '统计周期'}
          value={activeStats ? formatCurrency(activeStats.total_expense) : '—'}
          hint="周期内支出合计"
          loading={periodStats.loading}
          accent="navy"
        />
        <MetricTile
          label="周期收入"
          value={activeStats ? formatCurrency(activeStats.total_income) : '—'}
          hint="代发工资与其他进账"
          loading={periodStats.loading}
          accent="gold"
        />
        <MetricTile
          label="日均支出"
          value={activeStats ? formatCurrency(activeStats.daily_average) : '—'}
          hint="按周期内实际天数摊销"
          loading={periodStats.loading}
        />
        <MetricTile
          label="单笔最高"
          value={activeStats ? formatCurrency(activeStats.max_single) : '—'}
          hint="周期内最大一笔支出"
          loading={periodStats.loading}
        />
      </div>

      {/* ---------------- 图表区 ---------------- */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <div className="xl:col-span-2 surface">
          <SectionHeader
            eyebrow="Trend"
            title="月度收支趋势"
            subtitle="近 6 个自然月，深色为支出、金色为收入"
          />
          <div className="px-4 pb-5">
            {periodStats.loading ? (
              <Skeleton className="h-[180px] w-full" />
            ) : (
              <TrendChart data={activeStats?.trend ?? []} />
            )}
          </div>
        </div>

        <div className="surface">
          <SectionHeader eyebrow="Breakdown" title="消费分类占比" />
          <div className="px-5 pb-5 flex justify-center">
            {periodStats.loading ? (
              <Skeleton className="h-[168px] w-[168px] rounded-full" />
            ) : (
              <DonutChart data={activeStats?.categories ?? []} />
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* 分类明细 */}
        <div className="surface">
          <SectionHeader eyebrow="Categories" title="分类明细" />
          <div className="px-5 pb-5 max-h-[380px] overflow-y-auto scrollbar-thin">
            {periodStats.loading ? (
              <Skeleton className="h-48 w-full" />
            ) : activeStats && activeStats.categories.length > 0 ? (
              <CategoryBars data={activeStats.categories} />
            ) : (
              <EmptyState title="该周期暂无消费记录" />
            )}
          </div>
        </div>

        {/* 异常交易 */}
        <div className="xl:col-span-2 surface">
          <SectionHeader
            eyebrow="Anomaly Detection"
            title="异常交易识别"
            subtitle="基于分类基线、非常规时段与单笔金额的规则引擎"
            action={
              activeStats && activeStats.anomalies.length > 0 ? (
                <Badge tone="rose">{activeStats.anomalies.length} 笔可疑</Badge>
              ) : (
                <Badge tone="green">未发现异常</Badge>
              )
            }
          />
          <div className="px-3 pb-3">
            {periodStats.loading ? (
              <div className="px-2 space-y-2">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </div>
            ) : activeStats && activeStats.anomalies.length > 0 ? (
              <div className="divide-y divide-[#eef1f5]">
                {activeStats.anomalies.map((a) => (
                  <div key={a.transaction_id} className="px-2 py-3 flex items-start gap-3">
                    <div className="w-8 h-8 rounded-lg bg-rose-50 text-rose-600 grid place-items-center shrink-0 mt-0.5">
                      <AlertTriangle className="w-4 h-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-[0.8125rem] font-medium text-ink">{a.merchant}</span>
                        <Badge tone="neutral">{a.category}</Badge>
                        <span
                          className={`text-[0.6875rem] font-semibold tnum ${
                            a.score >= 75 ? 'text-rose-600' : 'text-amber-600'
                          }`}
                        >
                          风险分 {a.score}
                        </span>
                      </div>
                      <div className="text-[0.6875rem] text-ink-muted mt-1 leading-relaxed">{a.reason}</div>
                      <div className="text-[0.625rem] text-ink-muted mt-1 tnum">{formatDate(a.occurred_at)}</div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="amount text-[0.875rem] text-ink">¥ {a.amount.toLocaleString('zh-CN')}</div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                title="未发现显著异常交易"
                hint="系统已按分类基线、非常规时段与单笔金额规则完成扫描。"
                icon={<Filter className="w-5 h-5" />}
              />
            )}
          </div>
        </div>
      </div>

      {/* ---------------- 流水明细 ---------------- */}
      <div className="surface">
        <SectionHeader
          eyebrow="Transactions"
          title="交易流水明细"
          subtitle={`共 ${list.data?.total ?? 0} 笔记录 · 全部为模拟流水`}
          action={
            <button className="btn btn-sm btn-secondary">
              <Download className="w-3.5 h-3.5" />
              导出
            </button>
          }
        />

        {/* 分类筛选 */}
        <div className="px-5 pb-3 flex flex-wrap gap-1.5">
          {CATEGORIES.map((c) => (
            <button
              key={c}
              onClick={() => {
                setCategory(c)
                setPage(1)
              }}
              className={`px-2.5 h-7 rounded-md text-[0.6875rem] font-medium border transition-colors ${
                category === c
                  ? 'bg-navy-900 text-white border-navy-900'
                  : 'bg-white text-ink-muted border-[#e3e8ef] hover:border-navy-300 hover:text-ink'
              }`}
            >
              {c}
            </button>
          ))}
        </div>

        <div className="overflow-x-auto scrollbar-thin">
          {list.loading ? (
            <LoadingState />
          ) : list.error ? (
            <ErrorState message={list.error} onRetry={list.reload} />
          ) : list.data && list.data.items.length > 0 ? (
            <table className="table-base">
              <thead>
                <tr>
                  <th>交易对象</th>
                  <th>分类</th>
                  <th>渠道</th>
                  <th>时间</th>
                  <th className="text-right">金额</th>
                  <th className="text-right">余额</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((tx) => (
                  <tr key={tx.id}>
                    <td>
                      <div className="flex items-center gap-2.5">
                        <span className="w-7 h-7 rounded-md bg-[#eef1f5] grid place-items-center shrink-0">
                          {tx.direction === 'income' ? (
                            <ArrowDownLeft className="w-3.5 h-3.5 text-emerald-600" />
                          ) : (
                            <ArrowUpRight className="w-3.5 h-3.5 text-ink-soft" />
                          )}
                        </span>
                        <div className="min-w-0">
                          <div className="text-[0.8125rem] font-medium text-ink truncate max-w-[240px]">
                            {tx.merchant || tx.counterparty || '未知商户'}
                          </div>
                          {tx.remark && (
                            <div className="text-[0.625rem] text-ink-muted truncate max-w-[240px]">{tx.remark}</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td>
                      <Badge tone="neutral">{tx.category}</Badge>
                    </td>
                    <td className="text-[0.75rem] text-ink-muted">{tx.channel}</td>
                    <td className="text-[0.75rem] text-ink-muted tnum whitespace-nowrap">
                      {formatDate(tx.occurred_at)}
                    </td>
                    <td className="text-right">
                      <span
                        className={`amount text-[0.8125rem] ${
                          tx.direction === 'income' ? 'amount-income' : 'amount-expense'
                        }`}
                      >
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
          ) : (
            <EmptyState title="没有符合条件的流水" hint="试着调整筛选条件或更换关键词。" />
          )}
        </div>

        {/* 分页 */}
        {list.data && list.data.total > pageSize && (
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
      </div>
    </div>
  )
}

function formatPeriodLabel(month: string): string {
  if (month.includes('近')) return month
  return formatMonth(month)
}

function MetricTile({
  label,
  value,
  hint,
  loading = false,
  accent = 'ink',
}: {
  label: string
  value: string
  hint: string
  loading?: boolean
  accent?: 'ink' | 'navy' | 'gold'
}) {
  return (
    <div className="surface px-5 py-4">
      <div className="text-[0.6875rem] uppercase tracking-[0.1em] text-ink-muted font-semibold">{label}</div>
      {loading ? (
        <Skeleton className="h-7 w-24 mt-2" />
      ) : (
        <div
          className={`mt-1.5 text-[1.375rem] leading-none font-semibold tnum tracking-tight ${
            accent === 'gold' ? 'text-champagne-600' : accent === 'navy' ? 'text-navy-900' : 'text-ink'
          }`}
        >
          {value}
        </div>
      )}
      <div className="text-[0.6875rem] text-ink-muted mt-1.5">{hint}</div>
    </div>
  )
}
