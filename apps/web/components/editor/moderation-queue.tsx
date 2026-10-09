"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"

import { LoadingState } from "@/components/ui/loading-state"
import { ApiError, api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { relativeTime } from "@/lib/community"
import type { ReportOut } from "@/types/api"

const BTN =
  "min-h-9 rounded-lg border border-white/10 bg-white/[0.05] px-3 text-xs text-white/80 hover:bg-white/[0.1] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"

/** Reported comments for editors/admins. Several independent reports hide a comment
 * automatically; it waits here for a person to restore (the reports were wrong) or
 * delete it. Comment text is shown as plain text. */
export function ModerationQueue() {
  const { user, loading: authLoading } = useAuth()
  const allowed = user?.role === "editor" || user?.role === "admin"
  const [status, setStatus] = useState<"open" | "resolved" | "dismissed">("open")
  const [items, setItems] = useState<ReportOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setItems((await api.getReports(status)).items)
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load reports.")
    }
  }, [status])

  useEffect(() => {
    if (authLoading || !allowed) return
    let cancelled = false
    void (async () => {
      await Promise.resolve()
      if (!cancelled) await load()
    })()
    return () => {
      cancelled = true
    }
  }, [authLoading, allowed, load])

  async function decide(report: ReportOut, action: "hide" | "restore" | "delete") {
    try {
      await api.moderateComment(report.comment_id, action)
      setItems((current) => (current ?? []).filter((r) => r.comment_id !== report.comment_id))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That didn't work.")
    }
  }

  if (authLoading) return <LoadingState label="Loading…" />
  if (!allowed) return <p role="alert" className="text-sm text-white/70">Moderation is for editors.</p>

  return (
    <div className="space-y-4">
      <Link href="/editor" className="text-xs text-white/50 hover:text-white/80">← All articles</Link>
      <h1 className="text-xl font-bold text-white">Comment moderation</h1>
      <div role="group" aria-label="Report status" className="flex gap-2">
        {(["open", "resolved", "dismissed"] as const).map((s) => (
          <button key={s} type="button" aria-pressed={status === s} onClick={() => { setItems(null); setStatus(s) }} className={`${BTN} ${status === s ? "bg-white/[0.12]" : ""}`}>
            {s[0].toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {items === null && !error && <LoadingState label="Loading reports…" />}
      {items && items.length === 0 && <p className="text-sm text-white/45">Nothing here.</p>}
      <ul className="space-y-3">
        {items?.map((r) => (
          <li key={r.id} className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4">
            <p className="text-[11px] text-white/45">
              {r.comment_author} · {r.target_type} #{r.target_id} · {relativeTime(r.created_at)} · {r.report_count}{" "}
              {r.report_count === 1 ? "report" : "reports"} · currently <strong>{r.comment_status}</strong>
            </p>
            <p className="mt-1.5 whitespace-pre-wrap break-words text-sm text-white/90">{r.comment_body}</p>
            {r.reason && <p className="mt-1 text-xs text-white/50">Reported for: {r.reason}</p>}
            {status === "open" && (
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" className={BTN} onClick={() => void decide(r, "restore")}>Keep (dismiss reports)</button>
                <button type="button" className={BTN} onClick={() => void decide(r, "hide")}>Hide</button>
                <button type="button" className={`${BTN} text-red-200`} onClick={() => void decide(r, "delete")}>Delete</button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
