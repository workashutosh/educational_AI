import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"

import {
  api,
  clearSession,
  loadSession,
  saveSession,
  type Session,
} from "@/lib/api"

type AuthContextValue = {
  session: Session | null
  loading: boolean
  setSession: (session: Session | null) => void
  refresh: () => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<Session | null>(() => loadSession())
  const [loading, setLoading] = useState(true)

  const setSession = useCallback((next: Session | null) => {
    if (next) saveSession(next)
    else clearSession()
    setSessionState(next)
  }, [])

  const refresh = useCallback(async () => {
    const token = loadSession()?.token
    if (!token) {
      setSession(null)
      return
    }
    const me = await api<Session>("/api/auth/me/")
    setSession(me)
  }, [setSession])

  const logout = useCallback(async () => {
    try {
      await api("/api/auth/logout/", { method: "POST" })
    } catch {
      // ignore network errors on logout
    }
    setSession(null)
  }, [setSession])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        if (loadSession()?.token) await refresh()
      } catch {
        if (!cancelled) setSession(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [refresh, setSession])

  const value = useMemo(
    () => ({ session, loading, setSession, refresh, logout }),
    [session, loading, setSession, refresh, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
