// ==========================================================================
// 金枢 FinTrust Agent · 前端类型定义（与后端 Pydantic schema 保持一致）
// ==========================================================================

export type RiskLevel = 'green' | 'yellow' | 'red'
export type TransactionDirection = 'income' | 'expense'
export type CardStatus = 'active' | 'frozen' | 'lost'

export interface Account {
  id: number
  account_no: string
  holder_name: string
  account_type: string
  bank_name: string
  currency: string
  balance: number
  available: number
  status: string
  card_count: number
  created_at: string
}

export interface BankCard {
  id: number
  account_id: number
  card_no: string
  masked_card_no: string
  card_type: string
  card_name: string
  network: string
  status: CardStatus
  daily_limit: number
  expire_month: string
  is_virtual: boolean
  is_simulated: boolean
  created_at: string
}

export interface Transaction {
  id: number
  account_id: number
  card_id: number | null
  direction: TransactionDirection
  category: string
  amount: number
  balance_after: number
  merchant: string
  counterparty: string
  remark: string
  status: string
  channel: string
  is_simulated: boolean
  occurred_at: string
}

export interface Payee {
  id: number
  account_id: number
  name: string
  account_no: string
  masked_account_no: string
  bank_name: string
  card_last4: string
  is_frequent: boolean
  single_limit: number
  total_count: number
  last_used_at: string | null
  created_at: string
}

export interface CategoryBreakdown {
  category: string
  amount: number
  count: number
  ratio: number
}

export interface MonthlyTrend {
  month: string
  expense: number
  income: number
}

export interface AnomalyItem {
  transaction_id: number
  occurred_at: string
  merchant: string
  category: string
  amount: number
  direction: string
  score: number
  reason: string
}

export interface SpendingStats {
  month: string
  total_expense: number
  total_income: number
  transaction_count: number
  daily_average: number
  max_single: number
  categories: CategoryBreakdown[]
  trend: MonthlyTrend[]
  anomalies: AnomalyItem[]
}

export interface OverviewResponse {
  account: Account
  cards: BankCard[]
  recent_transactions: Transaction[]
  stats: SpendingStats
  payees: Payee[]
  simulation_notice: string
}

export interface TransactionPage {
  items: Transaction[]
  total: number
  page: number
  page_size: number
  total_amount: number
}

export interface RiskLevelInfo {
  level: RiskLevel
  label: string
  color: string
  reason: string
  rules: string[]
}

export interface TransferPreview {
  order_no: string
  risk_level: RiskLevel
  risk: RiskLevelInfo
  daily_total_before: number
  daily_total_after: number
  daily_limit_remaining: number
  payee_name: string
  payee_account_no: string
  masked_payee_account_no: string
  amount: number
  remark: string
  next_action: string
  requires_confirmation: boolean
  requires_mfa: boolean
  is_simulated: boolean
  simulation_notice: string
}

export interface TransferResult {
  order_no: string
  status: string
  transaction_id: number | null
  amount: number
  payee_name: string
  balance_after: number
  is_simulated: boolean
  simulation_notice: string
  message: string
}

export interface TransferPolicyInfo {
  yellow_single_max: number
  red_single_min: number
  red_daily_total: number
  yellow_daily_max: number
  levels: RiskLevelInfo[]
}

export interface AuditLog {
  id: number
  actor: string
  action: string
  target_type: string
  target_id: string
  risk_level: RiskLevel
  decision: string
  reason: string
  detail: Record<string, unknown>
  ip_address: string
  is_simulation: boolean
  created_at: string
}

export interface AuditPage {
  items: AuditLog[]
  total: number
  page: number
  page_size: number
  summary: {
    by_risk_level: Record<string, number>
    by_decision: Record<string, number>
    total: number
  }
}

export interface TraceStep {
  step: number
  node: string
  title: string
  status: string
  detail: string
  duration_ms: number
  payload: Record<string, unknown>
}

export interface AgentActionCard {
  kind: string
  title: string
  fields: Record<string, unknown>
}

export interface AgentResponse {
  session_id: string
  message_id: number
  reply: string
  intent: string
  intent_label: string
  confidence: number
  risk_level: RiskLevel
  demo_mode: boolean
  demo_mode_notice: string
  trace: TraceStep[]
  actions: AgentActionCard[]
  data: Record<string, any>
  created_at: string
}

export interface AgentMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  intent: string
  risk_level: RiskLevel
  demo_mode: boolean
  trace: TraceStep[]
  created_at: string
}

export interface AgentSession {
  session_id: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface AgentSessionDetail {
  session: AgentSession
  messages: AgentMessage[]
}

export interface HealthResponse {
  status: string
  app: string
  version: string
  environment: string
  demo_mode: boolean
  demo_mode_notice: string
  llm_configured: boolean
  database: string
  time: string
}

export interface AgentCapabilities {
  demo_mode: boolean
  demo_mode_notice: string
  llm_model: string
  llm_base_url: string | null
  tools: string[]
  circuit_breaker: { name: string; state: string; failures: number; threshold: number }
  intents: string[]
}

export interface ApiErrorPayload {
  code: string
  message: string
  detail?: Record<string, any>
  trace_id?: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: {
    id: number
    username: string
    account_ids: number[]
  }
}

export interface CurrentUser {
  id: number
  username: string
  status: string
  account_ids: number[]
}
