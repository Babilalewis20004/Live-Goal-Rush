"use client"

import { useState } from "react"
import Link from "next/link"

import { Button } from "@/components/ui/button"
import { api, ApiError } from "@/lib/api"
import {
  NOTIFIABLE_EVENTS,
  OVERRIDE_LABELS,
  describeOverride,
  globallyMuted,
  overrideCount,
  overrideState,
  withOverride,
  type FavouriteScope,
  type OverrideState,
} from "@/lib/notification-overrides"
import { isPushSupported, subscribeToPush } from "@/lib/push"
import type { FavouritesOut, NotificationPreferenceOut, RealtimeEventType } from "@/types/api"

const CARD = "rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md"

interface FavouriteItem {
  scope: FavouriteScope
  id: number
  title: string
  href: string
}

function favouriteItems(favourites: FavouritesOut | null): { heading: string; items: FavouriteItem[] }[] {
  if (!favourites) return []
  return [
    {
      heading: "Teams",
      items: favourites.teams.map((f) => ({
        scope: "team" as const,
        id: f.team.id,
        title: f.team.name,
        href: `/team/${f.team.id}`,
      })),
    },
    {
      heading: "Competitions",
      items: favourites.competitions.map((f) => ({
        scope: "competition" as const,
        id: f.competition.id,
        title: f.competition.name,
        href: `/competition/${f.competition.id}`,
      })),
    },
    {
      heading: "Matches",
      items: favourites.matches.map((f) => ({
        scope: "match" as const,
        id: f.match.id,
        title: `${f.match.home_team.name} v ${f.match.away_team.name}`,
        href: `/match/${f.match.id}`,
      })),
    },
  ].filter((group) => group.items.length > 0)
}

/** Global toggles plus (Phase 5) per-favourite overrides. Each favourite can
 * set each event to Default / On / Off; "Default" deletes the override. The
 * backend sends a notification if *any* followed scope allows it, unless the
 * global toggle turns that event off for everything -- the copy says so. */
export function NotificationSettings({
  initialPreferences,
  favourites = null,
}: {
  initialPreferences: NotificationPreferenceOut[]
  favourites?: FavouritesOut | null
}) {
  const [preferences, setPreferences] = useState(initialPreferences)
  const [pushEnabled, setPushEnabled] = useState(false)
  const [pushError, setPushError] = useState<string | null>(null)
  const [pushBusy, setPushBusy] = useState(false)
  const [overrideError, setOverrideError] = useState<string | null>(null)

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

  async function setOverride(item: FavouriteItem, event: RealtimeEventType, state: OverrideState) {
    setOverrideError(null)
    try {
      if (state === "default") {
        await api.resetNotificationPreference(item.scope, item.id, event)
        setPreferences((prev) => withOverride(prev, item.scope, item.id, event, "default"))
      } else {
        const updated = await api.updateNotificationPreference(item.scope, item.id, event, state === "on")
        setPreferences((prev) => withOverride(prev, item.scope, item.id, event, state, updated))
      }
    } catch (err) {
      setOverrideError(err instanceof ApiError ? err.message : "Couldn't save that change. Please try again.")
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

  const groups = favouriteItems(favourites)

  return (
    <div className="flex flex-col gap-4">
      <section className={CARD}>
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

      <section className={CARD}>
        <h2 className="mb-3 text-sm font-semibold text-white">What you get notified about</h2>
        <p className="mb-4 text-xs text-white/50">
          Applies to every team, competition and match you follow. All on by default. Turning an event off
          here silences it everywhere, whatever you set below.
        </p>
        <div className="flex flex-col gap-3">
          {NOTIFIABLE_EVENTS.map(({ type, label }) => (
            <label key={type} className="flex items-center justify-between text-sm text-white/80">
              {label}
              <input
                type="checkbox"
                checked={effectiveEnabled(type)}
                onChange={() => toggle(type)}
                className="size-4 accent-emerald-500"
              />
            </label>
          ))}
        </div>
      </section>

      <section className={CARD} aria-labelledby="overrides-heading">
        <h2 id="overrides-heading" className="mb-1 text-sm font-semibold text-white">
          Per-favourite settings
        </h2>
        <p className="mb-4 text-xs text-white/50">
          Fine-tune individual teams, competitions and matches. <strong className="text-white/70">Default</strong>{" "}
          notifies as normal. You&apos;re notified if <em>any</em> favourite that covers a match allows the
          event, so to silence a match completely, switch the event off for each favourite that covers it
          (or use the global toggles above).
        </p>
        {groups.length === 0 ? (
          <p className="text-xs text-white/40">
            Follow a team, competition or match and it will appear here.
          </p>
        ) : (
          <div className="flex flex-col gap-5">
            {groups.map((group) => (
              <div key={group.heading}>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/40">{group.heading}</h3>
                <ul className="flex flex-col gap-2">
                  {group.items.map((item) => {
                    const custom = overrideCount(preferences, item.scope, item.id)
                    return (
                      <li key={`${item.scope}-${item.id}`} className="rounded-xl border border-white/[0.06] bg-white/[0.02]">
                        <details>
                          <summary className="flex min-h-11 cursor-pointer items-center justify-between gap-3 px-3 py-2 text-sm text-white/90">
                            <span className="truncate">{item.title}</span>
                            <span className="shrink-0 text-[11px] text-white/40">
                              {custom > 0 ? `${custom} custom` : "Default"}
                            </span>
                          </summary>
                          <div className="flex flex-col gap-3 border-t border-white/[0.06] px-3 py-3">
                            {NOTIFIABLE_EVENTS.map(({ type, label }) => {
                              const state = overrideState(preferences, item.scope, item.id, type)
                              const muted = globallyMuted(preferences, type)
                              const selectId = `ov-${item.scope}-${item.id}-${type}`
                              return (
                                <div key={type} className="flex flex-col gap-1">
                                  <div className="flex items-center justify-between gap-3">
                                    <label htmlFor={selectId} className="text-sm text-white/80">
                                      {label}
                                    </label>
                                    <select
                                      id={selectId}
                                      value={state}
                                      onChange={(e) => void setOverride(item, type, e.target.value as OverrideState)}
                                      className="min-h-9 rounded-lg border border-white/10 bg-[#0b0f0d] px-2 text-sm text-white"
                                    >
                                      {(Object.keys(OVERRIDE_LABELS) as OverrideState[]).map((s) => (
                                        <option key={s} value={s}>
                                          {OVERRIDE_LABELS[s]}
                                        </option>
                                      ))}
                                    </select>
                                  </div>
                                  <p className="text-[11px] text-white/35">{describeOverride(state, muted)}</p>
                                </div>
                              )
                            })}
                            <Link href={item.href} className="self-start text-xs text-emerald-400 hover:underline">
                              View {item.title}
                            </Link>
                          </div>
                        </details>
                      </li>
                    )
                  })}
                </ul>
              </div>
            ))}
          </div>
        )}
        {overrideError && (
          <p role="alert" className="mt-3 text-xs text-red-400">
            {overrideError}
          </p>
        )}
      </section>
    </div>
  )
}
