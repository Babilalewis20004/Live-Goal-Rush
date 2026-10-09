"use client"

import Link from "next/link"
import { useState } from "react"

import { ApiError, api } from "@/lib/api"
import { useAuth } from "@/lib/auth-context"

/** Report someone's public profile (bio / name). Needs an account, one report each; a moderator reviews it. */
export function ReportProfile({ userId }: { userId: number }) {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState("")
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user?.id === userId) return null
  if (!user) {
    return (
      <p className="mt-3 text-[11px] text-white/60">
        <Link href="/login" className="underline">Sign in</Link> to report this profile.
      </p>
    )
  }
  if (done) return <p role="status" className="mt-3 text-xs text-white/60">Thanks — a moderator will take a look.</p>

  async function send() {
    setBusy(true)
    setError(null)
    try {
      await api.reportProfile(userId, reason)
      setDone(true)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't send the report.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-3">
      {!open ? (
        <button type="button" onClick={() => setOpen(true)} className="text-[11px] text-white/60 underline-offset-2 hover:text-white/70 hover:underline">
          Report this profile
        </button>
      ) : (
        <div className="space-y-2">
          <label className="block text-xs text-white/60" htmlFor="profile-report-reason">Why are you reporting this profile? (optional)</label>
          <input id="profile-report-reason" value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)}
            className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white" />
          <div className="flex gap-2">
            <button type="button" onClick={send} disabled={busy} className="rounded-lg bg-white/10 px-3 py-1.5 text-xs text-white disabled:opacity-50">{busy ? "Sending…" : "Send report"}</button>
            <button type="button" onClick={() => setOpen(false)} className="px-2 text-xs text-white/60">Cancel</button>
          </div>
          {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
        </div>
      )}
    </div>
  )
}
