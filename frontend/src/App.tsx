import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from '@/layouts/AppShell'
import Dashboard from '@/pages/Dashboard'
import AgentWorkbench from '@/pages/AgentWorkbench'
import BillAnalysis from '@/pages/BillAnalysis'
import Transfer from '@/pages/Transfer'
import Cards from '@/pages/Cards'
import Audit from '@/pages/Audit'
import Login from '@/pages/Login'
import { AccountProvider } from '@/context/AccountContext'
import { clearToken, getToken, setUnauthorizedHandler } from '@/api/client'

export default function App() {
  const [authed, setAuthed] = useState<boolean>(() => !!getToken())

  // 401 自动退出并跳转登录
  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearToken()
      setAuthed(false)
    })
  }, [])

  if (!authed) {
    return <Login onSuccess={() => setAuthed(true)} />
  }

  return (
    <AccountProvider>
      <Routes>
        <Route element={<AppShell onLogout={() => { clearToken(); setAuthed(false) }} />}>
          <Route index element={<Dashboard />} />
          <Route path="agent" element={<AgentWorkbench />} />
          <Route path="bills" element={<BillAnalysis />} />
          <Route path="transfer" element={<Transfer />} />
          <Route path="cards" element={<Cards />} />
          <Route path="audit" element={<Audit />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </AccountProvider>
  )
}
