import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { getCurrentAccountId, getCurrentUser, setCurrentAccountId } from '@/api/client'

interface AccountContextValue {
  accountId: number
  accountIds: number[]
  username: string
  setAccountId: (id: number) => void
}

const AccountContext = createContext<AccountContextValue | null>(null)

export function AccountProvider({ children }: { children: ReactNode }) {
  const user = getCurrentUser()
  const accountIds = user?.account_ids ?? []

  const [accountId, setAccountIdState] = useState<number>(() => {
    const saved = getCurrentAccountId()
    if (saved !== null && accountIds.includes(saved)) return saved
    return accountIds[0] ?? 1
  })

  const setAccountId = useCallback(
    (id: number) => {
      setCurrentAccountId(id)
      setAccountIdState(id)
    },
    [],
  )

  return (
    <AccountContext.Provider value={{ accountId, accountIds, username: user?.username ?? '', setAccountId }}>
      {children}
    </AccountContext.Provider>
  )
}

export function useCurrentAccount(): AccountContextValue {
  const ctx = useContext(AccountContext)
  if (!ctx) throw new Error('useCurrentAccount 必须在 AccountProvider 内使用')
  return ctx
}
