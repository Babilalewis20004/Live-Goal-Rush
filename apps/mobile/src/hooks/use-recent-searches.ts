import { useCallback, useEffect, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import { normalizeSearch, readRecent, withRecent, withoutRecent, writeRecent } from "@/lib/search-history"

/** Recent searches for whoever is using the app. Signed in: on the server, tied
 * to the account. Otherwise: on this device only. Newest first, capped, removable. */
export function useRecentSearches() {
  const { user, loading } = useAuth()
  const [recent, setRecent] = useState<string[]>([])

  useEffect(() => {
    if (loading) return
    let cancelled = false
    const handle = setTimeout(async () => {
      try {
        const queries = user ? (await api.getRecentSearches()).queries : await readRecent()
        if (!cancelled) setRecent(queries)
      } catch {
        if (!cancelled) setRecent([])
      }
    }, 0)
    return () => {
      cancelled = true
      clearTimeout(handle)
    }
  }, [user, loading])

  const remember = useCallback(
    (query: string) => {
      const clean = normalizeSearch(query)
      if (clean.length < 2) return
      setRecent((current) => {
        const next = withRecent(current, clean)
        if (!user) void writeRecent(next)
        return next
      })
      if (user) api.trackSearch(clean).catch(() => {})
    },
    [user],
  )

  const forget = useCallback(
    (query: string) => {
      setRecent((current) => {
        const next = withoutRecent(current, query)
        if (!user) void writeRecent(next)
        return next
      })
      if (user) api.clearRecentSearches(query).catch(() => {})
    },
    [user],
  )

  const forgetAll = useCallback(() => {
    setRecent([])
    if (user) api.clearRecentSearches().catch(() => {})
    else void writeRecent([])
  }, [user])

  return { recent, remember, forget, forgetAll }
}
