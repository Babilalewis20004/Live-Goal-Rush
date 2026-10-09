"use client"

import Link from "next/link"
import { useEffect, useState } from "react"

import { EmptyState } from "@/components/ui/empty-state"
import { LoadingState } from "@/components/ui/loading-state"
import { ApiError, api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { STATUS_LABEL } from "@/lib/editor"
import { formatArticleDate } from "@/lib/news"
import type { ArticleAdminSummary, ArticleStatus } from "@/types/api"

const FILTERS: { id: ArticleStatus | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "draft", label: "Drafts" },
  { id: "in_review", label: "In review" },
  { id: "scheduled", label: "Scheduled" },
  { id: "published", label: "Published" },
  { id: "archived", label: "Archived" },
]

const TOOL =
  "inline-flex min-h-9 items-center rounded-lg border border-white/10 bg-white/[0.04] px-3 text-xs text-white/80 hover:bg-white/[0.08] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"

/** The desk: the articles this person may manage (an author's own; an editor's own
 * plus everything past draft, so `In review` is their review queue; an admin's
 * everything), and the other creator tools. */
export function EditorDashboard() {
  const { user, loading: authLoading } = useAuth()
  const allowed = user?.role === "author" || user?.role === "editor" || user?.role === "admin"
  const reviewer = user?.role === "editor" || user?.role === "admin"
  const [filter, setFilter] = useState<ArticleStatus | "all">(reviewer ? "in_review" : "all")
  const [items, setItems] = useState<ArticleAdminSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (authLoading || !allowed) return
    let cancelled = false
    void (async () => {
      await Promise.resolve()
      try {
        const page = await api.listEditorArticles(filter === "all" ? undefined : filter)
        if (!cancelled) {
          setItems(page.items)
          setError(null)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Couldn't load articles.")
      }
    })()
    return () => {
      cancelled = true
    }
  }, [filter, authLoading, allowed])

  if (authLoading) return <LoadingState label="Loading…" />
  if (!allowed) {
    return (
      <div role="alert" className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-6 text-sm text-white/70">
        This area is for writers and editors. <Link href="/" className="underline">Back to livescores</Link>
      </div>
    )
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-white">Articles</h1>
        <Link
          href="/editor/new"
          className="inline-flex min-h-10 items-center rounded-xl bg-emerald-400 px-4 text-sm font-semibold text-[#070b09] hover:bg-emerald-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
        >
          New article
        </Link>
      </div>

      <nav aria-label="Creator tools" className="mt-3 flex flex-wrap gap-2">
        <Link href="/editor/media" className={TOOL}>
          Media library
        </Link>
        {reviewer && (
          <>
            <Link href="/editor/polls" className={TOOL}>
              Polls
            </Link>
            <Link href="/editor/moderation" className={TOOL}>
              Comment moderation
            </Link>
          </>
        )}
      </nav>

      <div role="group" aria-label="Filter by status" className="mt-4 flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            aria-pressed={filter === f.id}
            onClick={() => {
              setItems(null)
              setFilter(f.id)
            }}
            className={`min-h-9 rounded-full border px-3.5 text-xs font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400 ${filter === f.id ? "border-emerald-400/60 bg-emerald-400/15 text-white" : "border-white/10 bg-white/[0.03] text-white/70 hover:bg-white/[0.07]"}`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {error && (
          <p role="alert" className="text-sm text-red-300">
            {error}
          </p>
        )}
        {!error && items === null && <LoadingState label="Loading articles…" />}
        {items && items.length === 0 && (
          <EmptyState message={filter === "in_review" ? "Nothing is waiting for review." : "No articles here yet."} />
        )}
        {items && items.length > 0 && (
          <ul className="divide-y divide-white/[0.06] overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03]">
            {items.map((a) => (
              <li key={a.id}>
                <Link href={`/editor/${a.id}`} className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-white/[0.05] focus-visible:bg-white/[0.05] focus-visible:outline-none">
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-white">{a.title}</span>
                    <span className="block text-[11px] text-white/40">
                      <strong className="font-semibold text-white/60">{STATUS_LABEL[a.status]}</strong>
                      {a.published_at ? ` · ${formatArticleDate(a.published_at)}` : ""}
                      {a.author_name ? ` · by ${a.author_name}` : ""}
                      {a.category ? ` · ${a.category.name}` : ""}
                    </span>
                  </span>
                  <span className="shrink-0 text-[11px] text-white/50">{a.status === "in_review" && reviewer ? "Review →" : "Open →"}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
