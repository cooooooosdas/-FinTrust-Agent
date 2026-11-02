import { useCallback, useEffect, useState } from 'react'
import { accountApi } from '@/api'
import { ApiError } from '@/api/client'
import { useCurrentAccount } from '@/context/AccountContext'
import type { OverviewResponse } from '@/types'

/**
 * 全局共享的账户总览数据 —— 多个页面都需要余额与收款人信息。
 * 账户 ID 来自 AccountContext（支持双账户切换）。
 */
export function useOverview() {
  const { accountId } = useCurrentAccount()
  const [overview, setOverview] = useState<OverviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await accountApi.overview(accountId)
      setOverview(data)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '账户数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [accountId])

  useEffect(() => {
    load()
  }, [load])

  return { overview, loading, error, reload: load }
}
