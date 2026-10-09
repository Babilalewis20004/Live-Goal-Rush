"use client"

import { useEffect, useState } from "react"

import { ApiError, api } from "@/lib/api"
import type { RevisionDiff, RevisionOut } from "@/types/api"

const BTN =
  "min-h-9 rounded-lg border border-white/10 bg-white/[0.05] px-3 text-xs text-white/80 hover:bg-white/[0.1] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"

const ACTION_LABEL: Record<RevisionOut["action"], string> = {
  create: "Created",
  update: "Edited",
  status: "Status changed",
  restore: "Restored",
  scheduled: "Published by schedule",
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—"
  return typeof value === "string" ? value : JSON.stringify(value)
}

/** Version history for one article: who changed what and when, a side-by-side
 * comparison of any two versions (field changes plus a paragraph-level diff of
 * the body), and restore. A diff line is labelled in words ("added", "removed")
 * as well as coloured. */
export function RevisionsPanel({ articleId, canWrite, onRestored }: { articleId: number; canWrite: boolean; onRestored: () => void }) {
  const [revisions, setRevisions] = useState<RevisionOut[] | null>(null)
  const [from, setFrom] = useState<number | null>(null)
  const [to, setTo] = useState<number | null>(null)
  const [diff, setDiff] = useState<RevisionDiff | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      await Promise.resolve()
      try {
        const list = await api.listRevisions(articleId)
        if (cancelled) return
        setRevisions(list)
        if (list.length >= 2) {
          setTo(list[0].version)
          setFrom(list[1].version)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Couldn't load the history.")
      }
    })()
    return () => {
      cancelled = true
    }
  }, [articleId])

  async function compare() {
    if (from === null || to === null) return
    setBusy(true)
    setError(null)
    try {
      setDiff(await api.compareRevisions(articleId, from, to))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't compare those versions.")
    } finally {
      setBusy(false)
    }
  }

  async function restore(version: number) {
    if (!window.confirm(`Restore version ${version}? It becomes a new version; nothing is lost.`)) return
    setBusy(true)
    setError(null)
    try {
      await api.restoreRevision(articleId, version)
      onRestored()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't restore that version.")
    } finally {
      setBusy(false)
    }
  }

  if (error && !revisions) return <p role="alert" className="text-sm text-red-300">{error}</p>
  if (!revisions) return <p className="text-sm text-white/40">Loading history…</p>

  return (
    <section aria-label="Version history" className="space-y-4">
      <ol className="divide-y divide-white/[0.06] overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03]">
        {revisions.map((r) => (
          <li key={r.version} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm">
            <span className="min-w-0">
              <span className="font-medium text-white">Version {r.version}</span>{" "}
              <span className="text-white/60">· {ACTION_LABEL[r.action]}</span>
              <span className="block text-[11px] text-white/40">
                {r.editor_name ?? "System"} · <time dateTime={r.created_at}>{new Date(r.created_at).toLocaleString()}</time>
                {r.changes.length > 0 && r.action !== "create" ? ` · changed: ${r.changes.join(", ")}` : ""}
              </span>
            </span>
            {canWrite && r.version !== revisions[0].version && (
              <button type="button" disabled={busy} onClick={() => void restore(r.version)} className={BTN}>
                Restore
              </button>
            )}
          </li>
        ))}
      </ol>

      {revisions.length >= 2 && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            {([["Compare", from, setFrom], ["with", to, setTo]] as const).map(([label, value, set]) => (
              <label key={label} className="text-xs text-white/60">
                {label}
                <select
                  value={value ?? ""}
                  onChange={(e) => set(Number(e.target.value))}
                  className="ml-2 min-h-9 rounded-lg border border-white/10 bg-[#0b100d] px-2 text-xs text-white"
                >
                  {revisions.map((r) => (
                    <option key={r.version} value={r.version}>
                      Version {r.version}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <button type="button" onClick={() => void compare()} disabled={busy || from === null || to === null || from === to} className={BTN}>
              Show differences
            </button>
          </div>
          {error && <p role="alert" className="text-xs text-red-300">{error}</p>}

          {diff && (
            <div aria-live="polite" className="space-y-3 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4">
              <h3 className="text-sm font-semibold text-white">
                Version {diff.from_version} → version {diff.to_version}
              </h3>
              {diff.changes.length === 0 && diff.content_diff.length === 0 && <p className="text-sm text-white/50">No differences.</p>}
              <ul className="space-y-1.5 text-xs">
                {diff.changes.filter((c) => c.field !== "content").map((c) => (
                  <li key={c.field}>
                    <strong className="text-white/80">{c.field}:</strong>{" "}
                    <span className="text-red-200 line-through decoration-red-300/50">{show(c.before)}</span>
                    <span className="sr-only"> changed to </span> <span aria-hidden>→</span>{" "}
                    <span className="text-emerald-200">{show(c.after)}</span>
                  </li>
                ))}
              </ul>
              {diff.content_diff.length > 0 && (
                <div>
                  <h4 className="mb-1 text-xs font-semibold text-white/60">Body</h4>
                  <ul className="space-y-1 font-mono text-[12px] leading-snug">
                    {diff.content_diff.map((line, i) => (
                      <li
                        key={i}
                        className={`whitespace-pre-wrap rounded px-2 py-1 ${
                          line.kind === "add" ? "bg-emerald-400/10 text-emerald-100" : line.kind === "del" ? "bg-red-400/10 text-red-100" : "text-white/50"
                        }`}
                      >
                        <span className="mr-2 select-none text-white/40">{line.kind === "add" ? "+ added" : line.kind === "del" ? "− removed" : "  same"}</span>
                        {line.text}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
