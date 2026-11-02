// ==========================================================================
// 统一 API 客户端
// - 统一错误结构（后端 errors.py 定义的 { error: { code, message, detail } }）
// - 请求超时与网络异常兜底
// - 自动注入 X-Trace-Id
// 注意：API Key 永远不会出现在前端代码中（模型密钥仅存在于后端环境变量）
// ==========================================================================

import type { ApiErrorPayload } from '@/types'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1'
const DEFAULT_TIMEOUT = 30_000

// --------------------------------------------------------------------------
// 会话 token 管理（sessionStorage，刷新后恢复，不持久化密码）
// --------------------------------------------------------------------------
const TOKEN_KEY = 'fintrust.access_token'
const USER_KEY = 'fintrust.current_user'
const ACCOUNT_KEY = 'fintrust.current_account'

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(USER_KEY)
  sessionStorage.removeItem(ACCOUNT_KEY)
}

export function getCurrentUser(): { username: string; account_ids: number[] } | null {
  const raw = sessionStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export function setCurrentUser(user: { username: string; account_ids: number[] }): void {
  sessionStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function getCurrentAccountId(): number | null {
  const raw = sessionStorage.getItem(ACCOUNT_KEY)
  if (!raw) return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

export function setCurrentAccountId(accountId: number): void {
  sessionStorage.setItem(ACCOUNT_KEY, String(accountId))
}

// 401 时触发跳转登录的回调（由 App 层注入）
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn
}

export class ApiError extends Error {
  code: string
  detail: Record<string, any>
  status: number
  traceId?: string

  constructor(status: number, payload: Partial<ApiErrorPayload> & { message?: string }) {
    super(payload.message || '请求失败')
    this.name = 'ApiError'
    this.status = status
    this.code = payload.code || 'UNKNOWN_ERROR'
    this.detail = payload.detail || {}
    this.traceId = payload.trace_id
  }
}

function newTraceId(): string {
  const rand = Math.random().toString(36).slice(2, 10)
  return `web-${Date.now().toString(36)}-${rand}`
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'
  body?: unknown
  query?: Record<string, string | number | boolean | undefined | null>
  headers?: Record<string, string>
  timeout?: number
  signal?: AbortSignal
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = `${BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
  if (!query) return url
  const params = new URLSearchParams()
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      params.append(key, String(value))
    }
  })
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

/**
 * 统一请求入口。所有后端错误都会被转换成 ApiError。
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, headers = {}, timeout = DEFAULT_TIMEOUT, signal } = options

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  if (signal) {
    signal.addEventListener('abort', () => controller.abort())
  }

  try {
    const response = await fetch(buildUrl(path, query), {
      method,
      headers: {
        'Content-Type': 'application/json',
        'X-Trace-Id': newTraceId(),
        ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })

    const text = await response.text()
    let payload: any = null
    if (text) {
      try {
        payload = JSON.parse(text)
      } catch {
        payload = { message: text }
      }
    }

    if (!response.ok) {
      const err = payload?.error ?? payload
      // 401：会话失效，触发跳转登录
      if (response.status === 401 && onUnauthorized) {
        onUnauthorized()
      }
      throw new ApiError(response.status, {
        code: err?.code,
        message: err?.message,
        detail: err?.detail,
        trace_id: err?.trace_id,
      })
    }

    return payload as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(408, { code: 'TIMEOUT', message: '请求超时，请检查后端服务是否已启动' })
    }
    throw new ApiError(0, {
      code: 'NETWORK_ERROR',
      message: '无法连接到后端服务，请确认 FastAPI 已在 8000 端口启动',
    })
  } finally {
    clearTimeout(timer)
  }
}

/** 生成幂等键（写入受控写操作请求头）。 */
export function newIdempotencyKey(prefix = 'web'): string {
  const rand = Math.random().toString(36).slice(2, 12)
  return `${prefix}-${Date.now().toString(36)}-${rand}`
}

/** 生成一次独立用户意图的**稳定**幂等键（UUID v4）。 */
export function createIntentIdempotencyKey(): string {
  const rand = () => {
    const b = crypto.getRandomValues(new Uint8Array(16))
    b[6] = (b[6] & 0x0f) | 0x40
    b[8] = (b[8] & 0x3f) | 0x80
    const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
  }
  return rand()
}
