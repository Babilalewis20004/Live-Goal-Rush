import { useCallback, useEffect, useRef, useState } from "react"

import { ApiError } from "@/lib/api"

export interface AsyncState<T> {
  data: T | null
  /** The failure, if the last load failed. A 402 keeps `error.entitlement`. */
  error: ApiError | Error | null
  loading: boolean
  reload: () => void
}

/** Loads `load()` whenever `key` changes (or `reload()` / a changed `nudge` asks).
 * `key` is a string the caller builds from the inputs, so there is no spread
 * dependency array to get wrong. The latest `load` is read through a ref. Stale
 * answers are dropped; failures keep the previous data so a refresh blip doesn't blank the screen. */
export function useAsync<T>(load: () => Promise<T>, key: string, nudge = 0, enabled = true): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [token, setToken] = useState(0)
  const loadRef = useRef(load)
  useEffect(() => {
    loadRef.current = load
  })

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    void (async () => {
      await Promise.resolve() // not synchronous with the effect: keeps state updates out of the render phase
      setLoading(true)
      try {
        const result = await loadRef.current()
        if (!cancelled) {
          setData(result)
          setError(null)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e : new Error("Unable to load"))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [key, nudge, token, enabled])

  const reload = useCallback(() => setToken((t) => t + 1), [])
  return { data, error, loading, reload }
}

export function isPaymentRequired(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 402
}
