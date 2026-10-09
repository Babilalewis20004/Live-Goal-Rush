"use client"

import { useCallback, useEffect, useState } from "react"

import { ApiError, api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"
import { relativeTime } from "@/lib/community"
import type { ProfileReportOut } from "@/types/api"

const BTN =
  "min-h-9 rounded-lg border border-white/10 bg-white/[0.05] px-3 text-xs text-white/80 hover:bg-white/[0.1] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"

/** Reported profiles. Editors and admins resolve or dismiss; only admins can suspend an account
 * (which signs the person out everywhere and blocks them posting until restored). */
export function ProfileReports() {
  const { user, loading: authLoading } = useAuth()
  const allowed = user?.role === "editor" || user?.role === "admin"
  const isAdmin = user?.role === "admin"
  const [items, setItems] = useState<ProfileReportOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<number | null>(null)

  const load = useCallback(async () => {
    try {
      setItems((await api.listProfileReports("open")).items)
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load profile reports.")
    }
  }, [])

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

  async function act(report: ProfileReportOut, what: "resolve" | "dismiss" | "suspend" | "unsuspend") {
    setBusy(report.id)
    setError(null)
    try {
      if (what === "suspend") await api.suspendUser(report.profile_user_id, `Profile report #${report.id}`)
      else if (what === "unsuspend") await api.unsuspendUser(report.profile_user_id)
      else await api.resolveProfileReport(report.id, what)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That didn't work.")
    } finally {
      setBusy(null)
    }
  }

  if (authLoading || !allowed) return null
  return (
    <section aria-labelledby="profile-reports" className="mt-10">
      <h2 id="profile-reports" className="mb-3 text-sm font-semibold text-white">Reported profiles</h2>
      {error && <p role="alert" className="mb-2 text-sm text-red-300">{error}</p>}
      {items === null ? (
        <p className="text-xs text-white/60" aria-busy="true">Loading…</p>
      ) : items.length === 0 ? (
        <p className="rounded-2xl border border-white/[0.08] px-4 py-6 text-center text-sm text-white/60">No open profile reports.</p>
      ) : (
        <ul className="space-y-3">
          {items.map((r) => (
            <li key={r.id} className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4">
              <p className="text-sm text-white">
                {r.display_name} <span className="text-xs text-white/60">· user #{r.profile_user_id} · {relativeTime(r.created_at)}</span>
                {r.suspended && <span className="ml-2 rounded bg-red-500/20 px-1.5 text-[11px] uppercase text-red-200">Suspended</span>}
              </p>
              <p className="mt-1 text-xs text-white/60">Reason: {r.reason || "none given"}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" className={BTN} disabled={busy === r.id} onClick={() => act(r, "resolve")}>Resolve</button>
                <button type="button" className={BTN} disabled={busy === r.id} onClick={() => act(r, "dismiss")}>Dismiss</button>
                {isAdmin && !r.suspended && <button type="button" className={BTN} disabled={busy === r.id} onClick={() => act(r, "suspend")}>Suspend account</button>}
                {isAdmin && r.suspended && <button type="button" className={BTN} disabled={busy === r.id} onClick={() => act(r, "unsuspend")}>Restore account</button>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
