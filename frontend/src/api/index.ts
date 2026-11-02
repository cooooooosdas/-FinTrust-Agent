// ==========================================================================
// 后端接口封装
// ==========================================================================

import { request } from './client'
import type {
  AgentCapabilities,
  AgentResponse,
  AgentSession,
  AgentSessionDetail,
  AuditPage,
  CurrentUser,
  HealthResponse,
  LoginResponse,
  OverviewResponse,
  Payee,
  SpendingStats,
  TransactionPage,
  TransferPolicyInfo,
  TransferPreview,
  TransferResult,
  BankCard,
} from '@/types'

/* ------------------------------ 认证 ------------------------------ */
export const authApi = {
  login: (username: string, password: string) =>
    request<LoginResponse>('/auth/login', { method: 'POST', body: { username, password } }),
  logout: () => request<{ status: string }>('/auth/logout', { method: 'POST' }),
  me: () => request<CurrentUser>('/auth/me'),
  changePasswordChallenge: () => request<any>('/accounts/password/change/challenge', { method: 'POST' }),
  changePassword: (payload: { old_password: string; new_password: string; mfa_code: string; mfa_challenge_id: string }) =>
    request<any>('/accounts/password/change', { method: 'POST', body: payload }),
}

/* ------------------------------ 系统 ------------------------------ */
export const systemApi = {
  health: () => request<HealthResponse>('/health'),
  simulationNotice: () => request<{ tag: string; notice: string }>('/meta/simulation-notice'),
}

/* ------------------------------ 账户 ------------------------------ */
export const accountApi = {
  list: () => request<OverviewResponse['account'][]>('/accounts'),
  overview: (accountId = 1) => request<OverviewResponse>('/accounts/overview', { query: { account_id: accountId } }),
}

/* ------------------------------ 卡片 ------------------------------ */
export const cardApi = {
  list: (accountId = 1) => request<BankCard[]>('/cards', { query: { account_id: accountId } }),
  detail: (cardId: number) => request<BankCard>(`/cards/${cardId}`),
  applyVirtual: (payload: { card_name: string; daily_limit: number; expire_month: string }, confirm = false) =>
    request<any>('/cards/virtual', {
      method: 'POST',
      body: payload,
      query: { confirm },
    }),
  freeze: (cardId: number, confirm = false) =>
    request<any>('/cards/freeze', { method: 'POST', query: { card_id: cardId, confirm } }),
  reportLost: (cardId: number, reason: string, mfaCode?: string, mfaChallengeId?: string) =>
    request<any>('/cards/lost', {
      method: 'POST',
      body: { card_id: cardId, reason },
      query: mfaCode ? { mfa_code: mfaCode, mfa_challenge_id: mfaChallengeId } : undefined,
    }),
}

/* ---------------------------- 交易 / 账单 ---------------------------- */
export const transactionApi = {
  list: (params: {
    account_id?: number
    start_date?: string
    end_date?: string
    category?: string
    direction?: string
    keyword?: string
    min_amount?: number
    max_amount?: number
    page?: number
    page_size?: number
  }) => request<TransactionPage>('/transactions', { query: params }),
  stats: (accountId = 1, period?: string) =>
    request<SpendingStats>('/transactions/stats', { query: { account_id: accountId, period } }),
  anomalies: (accountId = 1) => request<any[]>('/transactions/anomalies', { query: { account_id: accountId } }),
}

/* ------------------------------ 收款人 ------------------------------ */
export const payeeApi = {
  list: (accountId = 1) => request<Payee[]>('/payees', { query: { account_id: accountId } }),
  create: (payload: {
    account_id: number
    name: string
    account_no: string
    bank_name?: string
    card_last4?: string
  }) => request<Payee>('/payees', { method: 'POST', body: payload }),
}

/* ------------------------------ 转账 ------------------------------ */
export const transferApi = {
  policy: () => request<TransferPolicyInfo>('/transfers/policy'),
  dailyTotal: (accountId = 1) => request<any>('/transfers/daily-total', { query: { account_id: accountId } }),
  preview: (payload: {
    account_id: number
    payee_id?: number
    payee_name?: string
    payee_account_no?: string
    amount: number
    remark?: string
  }) => request<TransferPreview>('/transfers/preview', { method: 'POST', body: payload }),
  execute: (
    payload: { order_no: string; confirm?: boolean; mfa_code?: string; mfa_challenge_id?: string },
    idempotencyKey: string,
  ) =>
    request<TransferResult>('/transfers/execute', {
      method: 'POST',
      body: payload,
      headers: { 'Idempotency-Key': idempotencyKey },
    }),
}

/* ------------------------------ AI 助手 ------------------------------ */
export const agentApi = {
  chat: (payload: { message: string; session_id?: string; account_id?: number }) =>
    request<AgentResponse>('/agent/chat', { method: 'POST', body: payload }),
  sessions: () => request<AgentSession[]>('/agent/sessions'),
  sessionDetail: (sessionId: string) => request<AgentSessionDetail>(`/agent/sessions/${sessionId}`),
  capabilities: () => request<AgentCapabilities>('/agent/capabilities'),
}

/* ------------------------------ 安全审计 ------------------------------ */
export const auditApi = {
  list: (params: { risk_level?: string; action?: string; page?: number; page_size?: number } = {}) =>
    request<AuditPage>('/audit', { query: params }),
  integrity: () =>
    request<{ status: string; passed: boolean; detail: Record<string, unknown>; verified_at: string }>(
      '/audit/integrity',
    ),
}
