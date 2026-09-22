"use client"

import { useState } from "react"

import { Button } from "@/components/ui/button"
import { api, ApiError } from "@/lib/api"
import { isPushSupported, subscribeToPush } from "@/lib/push"
import type { NotificationPreferenceOut, RealtimeEventType } from "@/types/api"

const DEFAULT_ON_EVENT_TYPES: { type: RealtimeEventType; label: string }[] = [
  { type: "MATCH_STARTED", label: "Kick-off" },
  { type: "GOAL", label: "Goals" },
  { type: "CARD", label: "Cards" },
  { type: "HALF_TIME", label: "Half-time" },
  { type: "MATCH_FINISHED", label: "Full-time" },
]

/** GLOBAL-scope toggles only -- per-team/competition/match overrides are
 * available implicitly (favouriting something opts you into these same
 * defaults for it; muting a specific team/competition/match is a fast
 * follow, not required for a "sensible defaults" preference system per
 * spec §14). */
export function NotificationSettings({ initialPreferences }: { initialPreferences: NotificationPreferenceOut[] }) {
  const [preferences, setPreferences] = useState(initialPreferences)
  const [pushEnabled, setPushEnabled] = useState(false)
  const [pushError, setPushError] = useState<string | null>(null)
  const [pushBusy, setPushBusy] = useState(false)

  function effectiveEnabled(eventType: RealtimeEventType): boolean {
    const pref = preferences.find((p) => p.scope_type === "global" && p.event_type === eventType)
    return pref ? pref.enabled : true
  }

  async function toggle(eventType: RealtimeEventType) {
    const next = !effectiveEnabled(eventType)
    try {
      const updated = await api.updateNotificationPreference("global", null, eventType, next)
      setPreferences((prev) => [...prev.filter((p) => !(p.scope_type === "global" && p.event_type === eventType)), updated])
    } catch {
      // Leave state as-is; the toggle will just show its previous value.
    }
  }

  async function handleEnablePush() {
    setPushError(null)
    setPushBusy(true)
    try {
      const ok = await subscribeToPush()
      setPushEnabled(ok)
      if (!ok) setPushError("Push notifications aren't available or permission was declined.")
    } catch (err) {
      setPushError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.")
    } finally {
      setPushBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md">
        <h2 className="mb-2 text-sm font-semibold text-white">Browser notifications</h2>
        <p className="mb-3 text-xs text-white/50">
          Get notified in this browser even when LivePitch isn&apos;t open.
        </p>
        {isPushSupported() ? (
          <Button onClick={handleEnablePush} disabled={pushBusy || pushEnabled}>
            {pushEnabled ? "Enabled" : pushBusy ? "Enabling…" : "Enable browser notifications"}
          </Button>
        ) : (
          <p className="text-xs text-white/40">Not supported in this browser.</p>
        )}
        {pushError && <p className="mt-2 text-xs text-red-400">{pushError}</p>}
      </section>

      <section className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md">
        <h2 className="mb-3 text-sm font-semibold text-white">What you get notified about</h2>
        <p className="mb-4 text-xs text-white/50">
          Applies to every team, competition and match you follow. All on by default.
        </p>
        <div className="flex flex-col gap-3">
          {DEFAULT_ON_EVENT_TYPES.map(({ type, label }) => {
            const enabled = effectiveEnabled(type)
            return (
              <label key={type} className="flex items-center justify-between text-sm text-white/80">
                {label}
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={() => toggle(type)}
                  className="size-4 accent-emerald-500"
                />
              </label>
            )
          })}
        </div>
      </section>
    </div>
  )
}
