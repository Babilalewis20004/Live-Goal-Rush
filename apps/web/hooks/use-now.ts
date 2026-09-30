"use client"

import { useEffect, useState } from "react"

/** A `Date` that re-renders its consumer every `intervalMs` -- for relative
 * timestamps ("updated 24 seconds ago"). The interval callback is the only
 * place state is set, so there's no synchronous setState inside the effect. */
export function useNow(intervalMs = 5_000): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
  return now
}
