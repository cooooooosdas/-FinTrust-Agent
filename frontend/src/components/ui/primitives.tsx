import type { ReactNode } from 'react'
import { AlertTriangle, Inbox, Loader2, ShieldCheck, RefreshCw } from 'lucide-react'
import type { RiskLevel } from '@/types'

/* ============================ 卡片容器 ============================ */
export function Surface({
  children,
  className = '',
  as: Tag = 'section',
}: {
  children: ReactNode
  className?: string
  as?: 'section' | 'div' | 'article' | 'aside'
}) {
  return <Tag className={`surface ${className}`}>{children}</Tag>
}

export function SectionHeader({
  title,
  subtitle,
  action,
  eyebrow,
}: {
  title: string
  subtitle?: string
  action?: ReactNode
  eyebrow?: string
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 pt-5 pb-4">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-1.5">{eyebrow}</div>}
        <h2 className="section-title">{title}</h2>
        {subtitle && <p className="text-[0.75rem] text-ink-muted mt-1">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

/* ============================ 风险徽标 ============================ */
const riskMeta: Record<RiskLevel, { cls: string; label: string; dot: string }> = {
  green: { cls: 'badge-green', label: '绿色 · 自动执行', dot: 'bg-emerald-500' },
  yellow: { cls: 'badge-amber', label: '黄色 · 需确认', dot: 'bg-amber-500' },
  red: { cls: 'badge-rose', label: '红色 · 需多因子验证', dot: 'bg-rose-500' },
}

export function RiskBadge({ level, label, className = '' }: { level: RiskLevel; label?: string; className?: string }) {
  const meta = riskMeta[level] ?? riskMeta.green
  return (
    <span className={`badge ${meta.cls} ${className}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
      {label ?? meta.label}
    </span>
  )
}

export function Badge({
  children,
  tone = 'neutral',
  className = '',
}: {
  children: ReactNode
  tone?: 'neutral' | 'navy' | 'gold' | 'green' | 'amber' | 'rose'
  className?: string
}) {
  const map = {
    neutral: 'badge-neutral',
    navy: 'badge-navy',
    gold: 'badge-gold',
    green: 'badge-green',
    amber: 'badge-amber',
    rose: 'badge-rose',
  }
  return <span className={`badge ${map[tone]} ${className}`}>{children}</span>
}

/* ============================ 状态占位 ============================ */
export function LoadingState({ label = '正在加载…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-14 text-ink-muted text-[0.8125rem]">
      <Loader2 className="w-4 h-4 animate-spin" />
      {label}
    </div>
  )
}

export function ErrorState({
  message,
  onRetry,
  title = '数据加载失败',
}: {
  message: string
  onRetry?: () => void
  title?: string
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-14 px-6 text-center">
      <div className="w-10 h-10 rounded-full bg-rose-50 text-rose-600 grid place-items-center">
        <AlertTriangle className="w-5 h-5" />
      </div>
      <div>
        <div className="text-[0.875rem] font-medium text-ink">{title}</div>
        <div className="text-[0.75rem] text-ink-muted mt-1 max-w-md">{message}</div>
      </div>
      {onRetry && (
        <button className="btn btn-sm btn-secondary mt-1" onClick={onRetry}>
          <RefreshCw className="w-3.5 h-3.5" />
          重试
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, hint, icon }: { title: string; hint?: string; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2.5 py-12 px-6 text-center">
      <div className="w-10 h-10 rounded-full bg-[#eef1f5] text-ink-muted grid place-items-center">
        {icon ?? <Inbox className="w-5 h-5" />}
      </div>
      <div className="text-[0.8125rem] font-medium text-ink-soft">{title}</div>
      {hint && <div className="text-[0.75rem] text-ink-muted max-w-sm">{hint}</div>}
    </div>
  )
}

/* ============================ 模拟提示 ============================ */
export function SimulationNotice({ text, className = '' }: { text: string; className?: string }) {
  return (
    <div
      className={`flex items-start gap-2 rounded-lg border border-champagne-200 bg-champagne-50 px-3 py-2.5 text-[0.75rem] text-champagne-800 ${className}`}
    >
      <ShieldCheck className="w-3.5 h-3.5 mt-0.5 shrink-0" />
      <span className="leading-relaxed">{text}</span>
    </div>
  )
}

/* ============================ 数值展示 ============================ */
export function formatCurrency(value: number, withSymbol = true): string {
  const fixed = Math.abs(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  const sign = value < 0 ? '-' : ''
  return `${sign}${withSymbol ? '¥' : ''}${fixed}`
}

export function formatCompact(value: number): string {
  if (Math.abs(value) >= 10000) {
    return `${(value / 10000).toFixed(2)} 万`
  }
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

export function formatDate(iso: string, withTime = true): string {
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return iso
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  if (!withTime) return date
  return `${date} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function formatMonth(month: string): string {
  const [y, m] = month.split('-')
  return `${y} 年 ${Number(m)} 月`
}

/* ============================ 骨架屏 ============================ */
export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton ${className}`} />
}
