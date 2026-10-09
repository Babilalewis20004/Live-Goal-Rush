"use client"

import Link from "next/link"
import { useEffect, useState } from "react"

import { useRecentSearches } from "@/hooks/use-recent-searches"
import { api } from "@/lib/api"

const CHIP =
  "inline-flex min-h-9 items-center rounded-full border border-white/10 bg-white/[0.03] px-3.5 text-xs text-white/80 hover:bg-white/[0.07] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"

/** What to show before anything is typed: the viewer's own recent searches and
 * what other people have been looking up (only queries several different
 * visitors chose a result for -- see the API's popular-search rule). */
export function SearchHome() {
  const { recent, forget, forgetAll } = useRecentSearches()
  const [popular, setPopular] = useState<string[]>([])

  useEffect(() => {
    let cancelled = false
    api
      .getPopularSearches()
      .then((r) => !cancelled && setPopular(r.queries))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="space-y-6">
      {recent.length > 0 && (
        <section aria-labelledby="recent-heading">
          <div className="mb-2 flex items-center justify-between">
            <h2 id="recent-heading" className="text-xs font-semibold uppercase tracking-wide text-white/40">
              Recent searches
            </h2>
            <button
              type="button"
              onClick={forgetAll}
              className="rounded px-1 text-xs text-white/50 hover:text-white focus-visible:outline-2 focus-visible:outline-emerald-400"
            >
              Clear all
            </button>
          </div>
          <ul className="flex flex-wrap gap-2">
            {recent.map((q) => (
              <li key={q} className="inline-flex items-center gap-1">
                <Link href={`/search?q=${encodeURIComponent(q)}`} className={CHIP}>
                  {q}
                </Link>
                <button
                  type="button"
                  aria-label={`Remove ${q} from recent searches`}
                  onClick={() => forget(q)}
                  className="grid h-7 w-7 place-items-center rounded-full text-white/40 hover:bg-white/[0.08] hover:text-white focus-visible:outline-2 focus-visible:outline-emerald-400"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {popular.length > 0 && (
        <section aria-labelledby="popular-heading">
          <h2 id="popular-heading" className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/40">
            Popular searches
          </h2>
          <ul className="flex flex-wrap gap-2">
            {popular.map((q) => (
              <li key={q}>
                <Link href={`/search?q=${encodeURIComponent(q)}`} className={CHIP}>
                  {q}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
