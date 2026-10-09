"use client"

import { useState } from "react"

import { api, ApiError } from "@/lib/api"
import { CONTENT_KINDS } from "@/lib/news"
import type { ContentNotificationKind, ContentPreferenceOut } from "@/types/api"

/** Which kinds of article may be pushed to this user. Everything is off until
 * switched on, article pushes are capped per day, and they are delivered to
 * the same devices as match notifications (so no registered device, no push). */
export function ContentNotificationSettings({ initial }: { initial: ContentPreferenceOut[] }) {
  const [enabled, setEnabled] = useState<Record<string, boolean>>(
    Object.fromEntries(initial.map((p) => [p.kind, p.enabled])),
  )
  const [pending, setPending] = useState<ContentNotificationKind | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function toggle(kind: ContentNotificationKind) {
    if (pending) return
    const next = !enabled[kind]
    setPending(kind)
    setError(null)
    setEnabled((current) => ({ ...current, [kind]: next }))
    try {
      await api.setContentPreference(kind, next)
    } catch (e) {
      setEnabled((current) => ({ ...current, [kind]: !next }))
      setError(e instanceof ApiError ? e.message : "Couldn't save that. Try again.")
    } finally {
      setPending(null)
    }
  }

  return (
    <section aria-labelledby="news-notifications" className="mt-6 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 id="news-notifications" className="text-sm font-semibold text-white">
        News notifications
      </h2>
      <p className="mt-1 text-xs text-white/50">
        Off by default. We never notify you about every article — at most a few a day, only for what you switch on and
        follow.
      </p>
      <ul className="mt-4 space-y-3">
        {CONTENT_KINDS.map(({ kind, label, hint }) => (
          <li key={kind} className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <label htmlFor={`content-${kind}`} className="block text-sm text-white">
                {label}
              </label>
              <p className="text-[11px] text-white/40">{hint}</p>
            </div>
            <input
              id={`content-${kind}`}
              type="checkbox"
              role="switch"
              checked={!!enabled[kind]}
              disabled={pending === kind}
              onChange={() => toggle(kind)}
              className="h-5 w-5 shrink-0 accent-emerald-400"
            />
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="mt-3 text-xs text-red-300">
          {error}
        </p>
      )}
    </section>
  )
}
