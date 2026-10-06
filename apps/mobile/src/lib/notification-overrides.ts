// Pure logic for the per-favourite notification settings (Phase 5).
// apps/mobile/src/lib/notification-overrides.ts is an identical copy (kept in
// sync by hand; a test fails if they drift). Framework-free so vitest covers it.
//
// Model, matching the backend (notification_dispatch_service.resolve_targets):
//   * an explicit preference row exists for (scope, id, event) or it doesn't;
//   * no row = "default": the event's built-in default (all five of
//     `NOTIFIABLE_EVENTS` are on) -- *not* the global toggle;
//   * a user is notified if ANY scope that qualifies them (a followed team,
//     competition or match) allows the event, and a GLOBAL "off" for the
//     event silences it for everything.

import type {
  NotificationPreferenceOut,
  NotificationScope,
  RealtimeEventType,
} from "@/types/api"

export type OverrideState = "default" | "on" | "off"
export type FavouriteScope = Exclude<NotificationScope, "global">

export const NOTIFIABLE_EVENTS: { type: RealtimeEventType; label: string }[] = [
  { type: "MATCH_STARTED", label: "Kick-off" },
  { type: "GOAL", label: "Goals" },
  { type: "CARD", label: "Cards" },
  { type: "HALF_TIME", label: "Half-time" },
  { type: "MATCH_FINISHED", label: "Full-time" },
]

export const OVERRIDE_LABELS: Record<OverrideState, string> = {
  default: "Default",
  on: "On",
  off: "Off",
}

function find(
  prefs: NotificationPreferenceOut[],
  scope: NotificationScope,
  scopeId: number | null,
  event: RealtimeEventType,
): NotificationPreferenceOut | undefined {
  return prefs.find((p) => p.scope_type === scope && p.scope_id === scopeId && p.event_type === event)
}

export function overrideState(
  prefs: NotificationPreferenceOut[],
  scope: FavouriteScope,
  scopeId: number,
  event: RealtimeEventType,
): OverrideState {
  const pref = find(prefs, scope, scopeId, event)
  if (!pref) return "default"
  return pref.enabled ? "on" : "off"
}

/** Whether the *global* toggle currently silences this event for everything. */
export function globallyMuted(prefs: NotificationPreferenceOut[], event: RealtimeEventType): boolean {
  return find(prefs, "global", null, event)?.enabled === false
}

/** A one-line, honest description of what the current choice does, shown next
 * to the control so "Default" is never a mystery. */
export function describeOverride(state: OverrideState, muted: boolean): string {
  if (muted) return "Silenced everywhere by your global setting"
  if (state === "on") return "Always notify for this"
  if (state === "off") return "Don't notify for this (unless another favourite allows it)"
  return "Notify (default)"
}

/** The preference list after setting `state`: `updated` is the server's row
 * for "on"/"off"; "default" removes the row (the server deleted it). Pure, so
 * the optimistic UI and the tests share it. */
export function withOverride(
  prefs: NotificationPreferenceOut[],
  scope: FavouriteScope,
  scopeId: number,
  event: RealtimeEventType,
  state: OverrideState,
  updated?: NotificationPreferenceOut,
): NotificationPreferenceOut[] {
  const rest = prefs.filter(
    (p) => !(p.scope_type === scope && p.scope_id === scopeId && p.event_type === event),
  )
  return state === "default" || !updated ? rest : [...rest, updated]
}

/** How many explicit overrides a favourite has -- for a "2 custom" badge. */
export function overrideCount(
  prefs: NotificationPreferenceOut[],
  scope: FavouriteScope,
  scopeId: number,
): number {
  return prefs.filter(
    (p) =>
      p.scope_type === scope &&
      p.scope_id === scopeId &&
      NOTIFIABLE_EVENTS.some((e) => e.type === p.event_type),
  ).length
}
