// ==========================================================================
// 轻量 SVG 图表（无第三方图表依赖，保证离线可构建）
// 配色遵循设计系统：深海军蓝为主、香槟金为辅
// ==========================================================================

import type { CategoryBreakdown, MonthlyTrend } from '@/types'

/* ------------------------------------------------------------------ */
/* 月度收支趋势：面积 + 折线                                            */
/* ------------------------------------------------------------------ */
export function TrendChart({ data, height = 180 }: { data: MonthlyTrend[]; height?: number }) {
  if (!data.length) {
    return <div className="h-[180px] grid place-items-center text-[0.75rem] text-ink-muted">暂无趋势数据</div>
  }

  const width = 640
  const padX = 34
  const padTop = 16
  const padBottom = 26
  const innerH = height - padTop - padBottom
  const innerW = width - padX * 2

  const max = Math.max(...data.map((d) => Math.max(d.expense, d.income)), 1)
  const step = data.length > 1 ? innerW / (data.length - 1) : 0

  const x = (i: number) => padX + step * i
  const y = (v: number) => padTop + innerH - (v / max) * innerH

  const linePath = (key: 'expense' | 'income') =>
    data.map((d, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(d[key]).toFixed(1)}`).join(' ')

  const areaPath = `${linePath('expense')} L ${x(data.length - 1).toFixed(1)} ${(padTop + innerH).toFixed(1)} L ${padX} ${(
    padTop + innerH
  ).toFixed(1)} Z`

  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((r) => {
    const gy = padTop + innerH - innerH * r
    return { y: gy, value: max * r }
  })

  // 最后一个自然月可能仍在进行中，用虚线段 + "至今" 标注，避免视觉误读
  const now = new Date()
  const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  const isPartial = data.length > 0 && data[data.length - 1].month === currentMonth
  const solidCount = isPartial ? data.length - 1 : data.length

  const segmentPath = (key: 'expense' | 'income', from: number, to: number) =>
    data
      .slice(from, to + 1)
      .map((d, i) => `${i === 0 ? 'M' : 'L'} ${x(from + i).toFixed(1)} ${y(d[key]).toFixed(1)}`)
      .join(' ')

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto" role="img" aria-label="月度收支趋势图">
      <defs>
        <linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#0f2745" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#0f2745" stopOpacity="0.01" />
        </linearGradient>
      </defs>

      {gridLines.map((g, i) => (
        <g key={i}>
          <line x1={padX} y1={g.y} x2={width - padX} y2={g.y} stroke="#e3e8ef" strokeWidth="1" />
          <text x={padX - 8} y={g.y + 3.5} textAnchor="end" fontSize="10" fill="#7c8ca3">
            {g.value >= 10000 ? `${(g.value / 10000).toFixed(1)}w` : Math.round(g.value)}
          </text>
        </g>
      ))}

      <path d={areaPath} fill="url(#trend-fill)" />

      {isPartial && solidCount > 0 ? (
        <>
          <path d={segmentPath('expense', 0, solidCount - 1)} fill="none" stroke="#0f2745" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          <path d={segmentPath('income', 0, solidCount - 1)} fill="none" stroke="#d4a856" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          <path d={segmentPath('expense', solidCount - 1, data.length - 1)} fill="none" stroke="#0f2745" strokeWidth="2" strokeDasharray="4 4" strokeLinecap="round" opacity="0.75" />
          <path d={segmentPath('income', solidCount - 1, data.length - 1)} fill="none" stroke="#d4a856" strokeWidth="2" strokeDasharray="4 4" strokeLinecap="round" opacity="0.75" />
        </>
      ) : (
        <>
          <path d={linePath('expense')} fill="none" stroke="#0f2745" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          <path d={linePath('income')} fill="none" stroke="#d4a856" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}

      {data.map((d, i) => (
        <g key={d.month}>
          <circle cx={x(i)} cy={y(d.expense)} r="3" fill="#fff" stroke="#0f2745" strokeWidth="1.8" />
          <circle cx={x(i)} cy={y(d.income)} r="3" fill="#fff" stroke="#d4a856" strokeWidth="1.8" />
          <text x={x(i)} y={height - 8} textAnchor="middle" fontSize="10" fill="#7c8ca3">
            {isPartial && i === data.length - 1 ? `${d.month.slice(5)}月至今` : `${d.month.slice(5)}月`}
          </text>
        </g>
      ))}
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* 消费分类占比：水平条                                                 */
/* ------------------------------------------------------------------ */
const CATEGORY_COLORS = [
  '#0f2745',
  '#28446a',
  '#3f6da1',
  '#5f8cbb',
  '#94b4d6',
  '#c1903f',
  '#d4a856',
  '#dfbf78',
  '#815729',
  '#694728',
  '#7c8ca3',
  '#40536b',
]

export function CategoryBars({ data, max: maxOverride }: { data: CategoryBreakdown[]; max?: number }) {
  if (!data.length) {
    return <div className="py-8 text-center text-[0.75rem] text-ink-muted">暂无消费数据</div>
  }
  const max = maxOverride ?? Math.max(...data.map((d) => d.amount), 1)

  return (
    <div className="space-y-2.5">
      {data.map((d, i) => (
        <div key={d.category} className="group">
          <div className="flex items-baseline justify-between gap-3 mb-1">
            <span className="text-[0.8125rem] text-ink font-medium truncate">{d.category}</span>
            <span className="text-[0.75rem] text-ink-muted tnum shrink-0">
              ¥{d.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              <span className="ml-2 text-[0.6875rem]">{(d.ratio * 100).toFixed(1)}%</span>
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-[#eef1f5] overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${Math.max(2, (d.amount / max) * 100)}%`,
                backgroundColor: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
              }}
            />
          </div>
          <div className="text-[0.6875rem] text-ink-muted mt-0.5">{d.count} 笔</div>
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* 分类占比：环形图                                                     */
/* ------------------------------------------------------------------ */
export function DonutChart({ data, size = 168 }: { data: CategoryBreakdown[]; size?: number }) {
  if (!data.length) {
    return <div className="grid place-items-center text-[0.75rem] text-ink-muted">暂无数据</div>
  }
  const total = data.reduce((sum, d) => sum + d.amount, 0) || 1
  const stroke = 22
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  let offset = 0

  const segments = data.map((d, i) => {
    const fraction = d.amount / total
    const len = fraction * circumference
    const seg = {
      color: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
      dash: `${len} ${circumference - len}`,
      offset: -offset,
      label: d.category,
      ratio: fraction,
    }
    offset += len
    return seg
  })

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="消费分类占比环形图">
      <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#eef1f5" strokeWidth={stroke} />
        {segments.map((s) => (
          <circle
            key={s.label}
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={s.color}
            strokeWidth={stroke}
            strokeDasharray={s.dash}
            strokeDashoffset={s.offset}
            strokeLinecap="butt"
          >
            <title>{`${s.label} ${(s.ratio * 100).toFixed(1)}%`}</title>
          </circle>
        ))}
      </g>
      <text x={size / 2} y={size / 2 - 4} textAnchor="middle" fontSize="11" fill="#7c8ca3">
        支出总额
      </text>
      <text x={size / 2} y={size / 2 + 16} textAnchor="middle" fontSize="15" fontWeight="600" fill="#0a1c34">
        ¥{(total / 10000).toFixed(2)}万
      </text>
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* 迷你走势线                                                          */
/* ------------------------------------------------------------------ */
export function Sparkline({ values, width = 120, height = 32, color = '#0f2745' }: {
  values: number[]
  width?: number
  height?: number
  color?: string
}) {
  if (values.length < 2) return <div style={{ width, height }} />
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const range = max - min || 1
  const step = width / (values.length - 1)
  const path = values
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${(i * step).toFixed(1)} ${(height - ((v - min) / range) * height).toFixed(1)}`)
    .join(' ')
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      <path d={path} fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
