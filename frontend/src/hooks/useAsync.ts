import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '@/api/client'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
  setData: (value: T | null) => void
}

/**
 * 通用异步数据加载 Hook：统一处理 loading / error / 重载。
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const alive = useRef(true)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  useEffect(() => {
    alive.current = true
    setLoading(true)
    setError(null)
    loaderRef
      .current()
      .then((result) => {
        if (!alive.current) return
        setData(result)
      })
      .catch((err) => {
        if (!alive.current) return
        setError(err instanceof ApiError ? err.message : '未知错误')
      })
      .finally(() => {
        if (alive.current) setLoading(false)
      })
    return () => {
      alive.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => setTick((v) => v + 1), [])
  return { data, loading, error, reload, setData }
}
