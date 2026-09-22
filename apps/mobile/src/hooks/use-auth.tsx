import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react"

import { api } from "@/lib/api"
import { getStoredAccessToken } from "@/lib/auth-storage"
import { registerForPushNotificationsAsync } from "@/lib/push-notifications"
import type { UserOut } from "@/types/api"

interface AuthContextValue {
  user: UserOut | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, displayName?: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null)
  const [loading, setLoading] = useState(true)

  const restoreSession = useCallback(async () => {
    const token = await getStoredAccessToken()
    if (!token) {
      setLoading(false)
      return
    }
    try {
      const me = await api.getMe()
      setUser(me)
      void registerForPushNotificationsAsync()
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // Deferred via setTimeout so the initial fetch's setState calls never
    // run synchronously within the effect (react-hooks/set-state-in-effect,
    // matching the pattern already used in app/(tabs)/index.tsx).
    const handle = setTimeout(restoreSession, 0)
    return () => clearTimeout(handle)
  }, [restoreSession])

  const login = useCallback(async (email: string, password: string) => {
    const response = await api.login(email, password)
    setUser(response.user)
    void registerForPushNotificationsAsync()
  }, [])

  const register = useCallback(async (email: string, password: string, displayName?: string) => {
    const response = await api.register(email, password, displayName)
    setUser(response.user)
    void registerForPushNotificationsAsync()
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setUser(null)
    }
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider")
  return ctx
}
