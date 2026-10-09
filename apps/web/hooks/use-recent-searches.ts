"use client"

import { useCallback, useEffect, useState } from "react"

import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { MAX_RECENT, addRecent, clearRecent, normalizeSearch, readRecent, removeRecent } from "@/lib/search-history"

/** Recent searches for whoever is looking. Signed in: kept on the server and
 * tied to the account. Anonymous: kept in this browser's localStorage only
 * (never sent anywhere). Either way: newest first, capped, removable. */
export function useRecentSearches() {
  const { user, loading } = useAuth()
  const [recent, setRecent] = useState<string[]>([])

  useEffect(() => {
    if (loading) return
    let cancelled = false
    void (async () => {
      await Promise.resolve() // state is only set from a continuation, not synchronously in the effect
      try {
        const queries = user ? (await api.getRecentSearches()).queries : readRecent()
        if (!cancelled) setRecent(queries)
      } catch {
        if (!cancelled) setRecent([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [user, loading])

  const remember = useCallback(
    (query: string) => {
      const clean = normalizeSearch(query)
      if (clean.length < 2) return
      if (user) {
        api.trackSearch(clean).catch(() => {})
        setRecent((current) => [clean, ...current.filter((q) => q.toLowerCase() !== clean.toLowerCase())].slice(0, MAX_RECENT))
      } else {
        setRecent(addRecent(clean))
      }
    },
    [user],
  )

  const forget = useCallback(
    (query: string) => {
      setRecent((current) => current.filter((q) => q.toLowerCase() !== query.toLowerCase()))
      if (user) api.clearRecentSearches(query).catch(() => {})
      else removeRecent(query)
    },
    [user],
  )

  const forgetAll = useCallback(() => {
    setRecent([])
    if (user) api.clearRecentSearches().catch(() => {})
    else clearRecent()
  }, [user])

  return { recent, remember, forget, forgetAll }
}
