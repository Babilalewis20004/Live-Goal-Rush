"use client"

import { useState } from "react"

import { ArticleCard } from "@/components/news/article-card"
import { EmptyState } from "@/components/ui/empty-state"
import { api } from "@/lib/api"
import type { ArticleSummary, Page } from "@/types/api"

type Kind = "team" | "player" | "competition" | "match"

const LOADERS: Record<Kind, (id: number, page: number) => Promise<Page<ArticleSummary>>> = {
  team: (id, page) => api.getTeamNews(id, page),
  player: (id, page) => api.getPlayerNews(id, page),
  competition: (id, page) => api.getCompetitionNews(id, page),
  match: (id, page) => api.getMatchNews(id, page),
}

/** The News tab body on team / player / competition / match pages. The first
 * page arrives server-rendered; later pages load on demand. Only articles
 * explicitly linked to this entity are ever listed (the API guarantees it),
 * so an empty list is shown honestly rather than padded with other stories. */
export function EntityNews({ kind, id, initial }: { kind: Kind; id: number; initial: Page<ArticleSummary> }) {
  const [items, setItems] = useState(initial.items)
  const [page, setPage] = useState(initial.page)
  const [total, setTotal] = useState(initial.total)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (items.length === 0) return <EmptyState message="No news linked to this yet." />

  async function more() {
    setLoading(true)
    setError(null)
    try {
      const next = await LOADERS[kind](id, page + 1)
      setItems((current) => [...current, ...next.items.filter((a) => !current.some((c) => c.id === a.id))])
      setPage(next.page)
      setTotal(next.total)
    } catch {
      setError("Couldn't load more news. Try again.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-3">
      <ul className="space-y-3">
        {items.map((article) => (
          <li key={article.id}>
            <ArticleCard article={article} />
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="text-xs text-red-300">
          {error}
        </p>
      )}
      {items.length < total && (
        <button
          type="button"
          onClick={more}
          disabled={loading}
          className="min-h-10 w-full rounded-xl border border-white/10 bg-white/[0.03] text-xs font-medium text-white/80 hover:bg-white/[0.07] disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
        >
          {loading ? "Loading…" : `Load more (${total - items.length} more)`}
        </button>
      )}
    </div>
  )
}
