import { useEffect, useState } from "react"

/** A `Date` that re-renders its consumer every `intervalMs` -- for relative
 * timestamps ("updated 24 seconds ago"). Mirrors apps/web/hooks/use-now.ts. */
export function useNow(intervalMs = 5_000): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
  return now
}
