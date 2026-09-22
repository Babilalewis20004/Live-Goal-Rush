"use client"

import { createContext, useCallback, useContext, useState, type ReactNode } from "react"

import { api } from "@/lib/api"
import type { UserOut } from "@/types/api"

interface AuthContextValue {
  user: UserOut | null
  /** Always `false` after the initial render -- `initialUser` comes from
   * the root layout's server-side `getServerUser()` call, which is
   * awaited unconditionally, so it is always an authoritative answer
   * (including `null` for "confirmed anonymous"), never an "unknown, ask
   * the client" placeholder. Kept in the interface so a future caller
   * that resyncs via `refreshUser` (e.g. after a 401) has somewhere to
   * signal that -- currently unused. */
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, displayName?: string) => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({
  children,
  initialUser = null,
}: {
  children: ReactNode
  initialUser?: UserOut | null
}) {
  const [user, setUser] = useState<UserOut | null>(initialUser)
  const [loading, setLoading] = useState(false)

  const refreshUser = useCallback(async () => {
    setLoading(true)
    try {
      setUser(await api.getMe())
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const response = await api.login(email, password)
    setUser(response.user)
  }, [])

  const register = useCallback(async (email: string, password: string, displayName?: string) => {
    const response = await api.register(email, password, displayName)
    setUser(response.user)
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setUser(null)
    }
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider")
  return ctx
}
