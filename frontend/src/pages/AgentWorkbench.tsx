import { useEffect, useRef, useState } from 'react'
import {
  Bot,
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  Loader2,
  Route,
  Send,
  Sparkles,
  User,
  XCircle,
} from 'lucide-react'
import { agentApi } from '@/api'
import { ApiError } from '@/api/client'
import { useCurrentAccount } from '@/context/AccountContext'
import type { AgentMessage, AgentResponse, TraceStep } from '@/types'
import { Badge, ErrorState, RiskBadge, formatDate } from '@/components/ui/primitives'

const SUGGESTIONS = [
  '给张明远转 800 元，备注项目结算款',
  '本月餐饮消费统计',
  '我有几张银行卡',
  '申请一张虚拟卡，单日限额 3000',
  '最近有哪些异常交易',
  '把尾号 8899 的卡挂失',
]

export default function AgentWorkbench() {
  const { accountId } = useCurrentAccount()
  const [sessionId, setSessionId] = useState<string | undefined>(undefined)
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const scrollRef = useRef<HTMLDivElement>(null)

  // 恢复最近一次会话
  useEffect(() => {
    agentApi
      .sessions()
      .then((list) => {
        if (list.length > 0) {
          setSessionId(list[0].session_id)
          return agentApi.sessionDetail(list[0].session_id)
        }
        return null
      })
      .then((detail) => {
        if (detail) setMessages(detail.messages)
      })
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, sending])

  const send = async (text: string) => {
    const content = text.trim()
    if (!content || sending) return
    setError(null)
    setInput('')
    setSending(true)

    const optimistic: AgentMessage = {
      id: Date.now(),
      role: 'user',
      content,
      intent: '',
      risk_level: 'green',
      demo_mode: false,
      trace: [],
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, optimistic])

    try {
      const res: AgentResponse = await agentApi.chat({ message: content, session_id: sessionId, account_id: accountId })
      setSessionId(res.session_id)
      setMessages((prev) => [
        ...prev,
        {
          id: res.message_id,
          role: 'assistant',
          content: res.reply,
          intent: res.intent,
          risk_level: res.risk_level,
          demo_mode: res.demo_mode,
          trace: res.trace,
          created_at: res.created_at,
        },
      ])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '消息发送失败')
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id))
    } finally {
      setSending(false)
    }
  }

  const toggleTrace = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-5 max-w-[1400px]">
      {/* ---------------- 对话主区 ---------------- */}
      <div className="surface flex flex-col h-[calc(100vh-13rem)] min-h-[560px] overflow-hidden">
        {/* 头部 */}
        <div className="px-5 py-4 border-b border-[#e3e8ef] flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-navy-900 grid place-items-center shrink-0">
            <Bot className="w-[18px] h-[18px] text-champagne-300" strokeWidth={1.9} />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[0.9375rem] font-semibold text-ink">金枢智能助手</span>
              <Badge tone="gold">Agent</Badge>
            </div>
            <p className="text-[0.6875rem] text-ink-muted mt-0.5">
              意图识别 → 任务规划 → 工具调用 → DAG 执行轨迹，权限由后端策略引擎独立判定
            </p>
          </div>
          {sending && (
            <div className="ml-auto flex items-center gap-1.5 text-[0.6875rem] text-ink-muted">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              思考中
            </div>
          )}
        </div>

        {/* 消息流 */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin px-5 py-5 space-y-5">
          {messages.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center text-center px-6">
              <div className="w-12 h-12 rounded-xl bg-navy-900 grid place-items-center mb-4">
                <Sparkles className="w-5 h-5 text-champagne-300" />
              </div>
              <h3 className="text-[0.9375rem] font-semibold text-ink">开始一次对话</h3>
              <p className="mt-1.5 text-[0.8125rem] text-ink-muted max-w-md leading-relaxed">
                用自然语言描述你的金融需求。助手会解析意图与参数、规划任务 DAG，
                并在执行前由后端安全策略引擎给出权限等级。
              </p>
            </div>
          )}

          {messages.map((msg) =>
            msg.role === 'user' ? (
              <div key={msg.id} className="flex gap-3 justify-end">
                <div className="max-w-[78%]">
                  <div className="bg-navy-900 text-white rounded-xl rounded-tr-sm px-4 py-2.5 text-[0.8125rem] leading-relaxed whitespace-pre-wrap">
                    {msg.content}
                  </div>
                  <div className="text-[0.625rem] text-ink-muted mt-1 text-right tnum">
                    {formatDate(msg.created_at)}
                  </div>
                </div>
                <div className="w-7 h-7 rounded-lg bg-[#eef1f5] grid place-items-center shrink-0 mt-0.5">
                  <User className="w-3.5 h-3.5 text-ink-soft" />
                </div>
              </div>
            ) : (
              <div key={msg.id} className="flex gap-3">
                <div className="w-7 h-7 rounded-lg bg-navy-900 grid place-items-center shrink-0 mt-0.5">
                  <Bot className="w-3.5 h-3.5 text-champagne-300" />
                </div>
                <div className="flex-1 min-w-0 space-y-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    {msg.intent && <Badge tone="navy">{msg.intent}</Badge>}
                    {msg.risk_level !== 'green' && <RiskBadge level={msg.risk_level} />}
                    {msg.demo_mode && <Badge tone="gold">本地演示模式</Badge>}
                  </div>

                  <div className="bg-white border border-[#e3e8ef] rounded-xl rounded-tl-sm px-4 py-3 text-[0.8125rem] text-ink leading-relaxed whitespace-pre-wrap">
                    {msg.content}
                  </div>

                  {msg.trace.length > 0 && (
                    <div className="rounded-xl border border-[#e3e8ef] overflow-hidden">
                      <button
                        className="w-full flex items-center gap-2 px-3.5 py-2.5 bg-[#fafbfc] hover:bg-[#f4f6f9] transition-colors text-left"
                        onClick={() => toggleTrace(msg.id)}
                      >
                        <Route className="w-3.5 h-3.5 text-navy-500" />
                        <span className="text-[0.75rem] font-medium text-ink-soft">DAG 执行轨迹</span>
                        <span className="text-[0.6875rem] text-ink-muted">
                          {msg.trace.length} 个节点 ·{' '}
                          {msg.trace.reduce((sum, s) => sum + s.duration_ms, 0)}ms
                        </span>
                        <ChevronDown
                          className={`w-3.5 h-3.5 ml-auto text-ink-muted transition-transform ${
                            expanded.has(msg.id) ? 'rotate-180' : ''
                          }`}
                        />
                      </button>
                      {expanded.has(msg.id) && (
                        <div className="divide-y divide-[#eef1f5] bg-white">
                          {msg.trace.map((step) => (
                            <TraceRow key={step.step} step={step} />
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="text-[0.625rem] text-ink-muted tnum">{formatDate(msg.created_at)}</div>
                </div>
              </div>
            ),
          )}

          {sending && (
            <div className="flex gap-3">
              <div className="w-7 h-7 rounded-lg bg-navy-900 grid place-items-center shrink-0 mt-0.5">
                <Bot className="w-3.5 h-3.5 text-champagne-300" />
              </div>
              <div className="flex items-center gap-1.5 px-4 py-3 bg-[#f4f6f9] rounded-xl rounded-tl-sm">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="w-1.5 h-1.5 rounded-full bg-navy-400 animate-bounce"
                    style={{ animationDelay: `${i * 0.14}s` }}
                  />
                ))}
              </div>
            </div>
          )}

          {error && <ErrorState message={error} onRetry={() => setError(null)} title="请求失败" />}
        </div>

        {/* 输入区 */}
        <div className="border-t border-[#e3e8ef] px-5 py-3.5 bg-[#fafbfc]">
          <div className="flex items-end gap-2.5">
            <textarea
              className="input input-lg resize-none min-h-[46px] max-h-32 flex-1"
              rows={1}
              placeholder="描述你的需求，例如：给张明远转 800 元，备注项目结算款"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send(input)
                }
              }}
            />
            <button
              className="btn btn-lg btn-primary px-4"
              onClick={() => send(input)}
              disabled={!input.trim() || sending}
            >
              {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              发送
            </button>
          </div>
          <div className="mt-2 text-[0.625rem] text-ink-muted">
            Enter 发送 · Shift + Enter 换行 · 所有写操作均由后端策略引擎强制校验
          </div>
        </div>
      </div>

      {/* ---------------- 侧栏：示例指令 + 能力 ---------------- */}
      <div className="space-y-5">
        <div className="surface">
          <div className="px-5 pt-5 pb-3">
            <div className="eyebrow mb-1.5">Try It</div>
            <h3 className="section-title">示例指令</h3>
            <p className="text-[0.75rem] text-ink-muted mt-1">点击即可发起一次完整链路</p>
          </div>
          <div className="px-3 pb-4 space-y-1.5">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                disabled={sending}
                className="w-full text-left rounded-lg border border-[#e3e8ef] bg-[#fafbfc] hover:bg-white hover:border-navy-200 px-3 py-2.5 text-[0.75rem] text-ink-soft transition-colors leading-relaxed disabled:opacity-50"
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <div className="surface">
          <div className="px-5 pt-5 pb-3">
            <div className="eyebrow mb-1.5">Pipeline</div>
            <h3 className="section-title">Agent 执行链路</h3>
          </div>
          <div className="px-5 pb-5">
            <PipelineStep index={1} title="意图识别与参数抽取" desc="规则引擎 + 可选模型增强" />
            <PipelineStep index={2} title="任务规划" desc="生成带依赖关系的 DAG" />
            <PipelineStep index={3} title="工具调用" desc="调用真实业务服务" />
            <PipelineStep
              index={4}
              title="权限判定"
              desc="后端策略引擎，绿 / 黄 / 红"
              highlight
            />
            <PipelineStep index={5} title="答复生成与轨迹留痕" desc="写入 Agent 消息与审计日志" last />
          </div>
        </div>
      </div>
    </div>
  )
}

function TraceRow({ step }: { step: TraceStep }) {
  const Icon =
    step.status === 'success' ? CheckCircle2 : step.status === 'failed' ? XCircle : CircleDashed
  const color =
    step.status === 'success' ? 'text-emerald-600' : step.status === 'failed' ? 'text-rose-600' : 'text-ink-muted'
  return (
    <div className="px-3.5 py-2.5 flex items-start gap-2.5">
      <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${color}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[0.75rem] font-medium text-ink">{step.title}</span>
          <code className="text-[0.625rem] text-ink-muted font-mono">{step.node}</code>
          {step.duration_ms > 0 && (
            <span className="text-[0.625rem] text-ink-muted tnum ml-auto">{step.duration_ms}ms</span>
          )}
        </div>
        {step.detail && <div className="text-[0.6875rem] text-ink-muted mt-0.5 leading-relaxed">{step.detail}</div>}
      </div>
    </div>
  )
}

function PipelineStep({
  index,
  title,
  desc,
  highlight = false,
  last = false,
}: {
  index: number
  title: string
  desc: string
  highlight?: boolean
  last?: boolean
}) {
  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center shrink-0">
        <div
          className={`w-5 h-5 rounded-full grid place-items-center text-[0.5625rem] font-bold ${
            highlight ? 'bg-champagne-300 text-navy-900' : 'bg-navy-100 text-navy-700'
          }`}
        >
          {index}
        </div>
        {!last && <div className="w-px flex-1 bg-[#e3e8ef] my-1" />}
      </div>
      <div className="pb-4 min-w-0">
        <div className="text-[0.8125rem] font-medium text-ink leading-tight">{title}</div>
        <div className="text-[0.6875rem] text-ink-muted mt-0.5">{desc}</div>
      </div>
    </div>
  )
}
