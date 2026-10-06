import { describe, expect, it } from "vitest"
import {
  NOTIFIABLE_EVENTS,
  describeOverride,
  globallyMuted,
  overrideCount,
  overrideState,
  withOverride,
} from "./notification-overrides"
import { previousSeasonLabel, selectableSeasons } from "./seasons"
import type { CompetitionSeasonsOut, NotificationPreferenceOut } from "@/types/api"

let nextId = 1
function pref(
  scope_type: NotificationPreferenceOut["scope_type"],
  scope_id: number | null,
  event_type: NotificationPreferenceOut["event_type"],
  enabled: boolean,
): NotificationPreferenceOut {
  return { id: nextId++, scope_type, scope_id, event_type, enabled }
}

describe("per-favourite overrides", () => {
  const prefs = [
    pref("team", 5, "GOAL", false),
    pref("team", 5, "CARD", true),
    pref("team", 6, "GOAL", true),
    pref("competition", 5, "GOAL", false), // same id, different scope: must not collide with team 5
    pref("global", null, "HALF_TIME", false),
  ]

  it("no row means default; a row is on/off", () => {
    expect(overrideState(prefs, "team", 5, "GOAL")).toBe("off")
    expect(overrideState(prefs, "team", 5, "CARD")).toBe("on")
    expect(overrideState(prefs, "team", 5, "MATCH_STARTED")).toBe("default")
    expect(overrideState(prefs, "team", 99, "GOAL")).toBe("default")
  })

  it("scopes with the same id are independent", () => {
    expect(overrideState(prefs, "competition", 5, "GOAL")).toBe("off")
    expect(overrideState(prefs, "match", 5, "GOAL")).toBe("default")
    expect(overrideState(prefs, "team", 6, "GOAL")).toBe("on")
  })

  it("a global mute is detected only for global-scope rows set to off", () => {
    expect(globallyMuted(prefs, "HALF_TIME")).toBe(true)
    expect(globallyMuted(prefs, "GOAL")).toBe(false) // only team/competition rows exist for GOAL
    expect(globallyMuted([pref("global", null, "GOAL", true)], "GOAL")).toBe(false)
  })

  it("describes what each choice does, and that a global mute wins", () => {
    expect(describeOverride("default", false)).toBe("Notify (default)")
    expect(describeOverride("on", false)).toBe("Always notify for this")
    expect(describeOverride("off", false)).toMatch(/unless another favourite allows it/)
    expect(describeOverride("on", true)).toBe("Silenced everywhere by your global setting")
  })

  it("setting on/off replaces the row; default removes it; others untouched", () => {
    const updated = pref("team", 5, "GOAL", true)
    const afterOn = withOverride(prefs, "team", 5, "GOAL", "on", updated)
    expect(overrideState(afterOn, "team", 5, "GOAL")).toBe("on")
    expect(afterOn).toHaveLength(prefs.length) // replaced, not duplicated
    expect(overrideState(afterOn, "competition", 5, "GOAL")).toBe("off")

    const afterReset = withOverride(prefs, "team", 5, "GOAL", "default")
    expect(overrideState(afterReset, "team", 5, "GOAL")).toBe("default")
    expect(afterReset).toHaveLength(prefs.length - 1)
    expect(overrideState(afterReset, "team", 5, "CARD")).toBe("on")
  })

  it("does not mutate its input", () => {
    const snapshot = [...prefs]
    withOverride(prefs, "team", 5, "GOAL", "default")
    expect(prefs).toEqual(snapshot)
  })

  it("counts only a favourite's own overrides for the five notifiable events", () => {
    expect(overrideCount(prefs, "team", 5)).toBe(2)
    expect(overrideCount(prefs, "team", 6)).toBe(1)
    expect(overrideCount(prefs, "match", 5)).toBe(0)
    expect(overrideCount([pref("team", 5, "MATCH_UPDATED", true)], "team", 5)).toBe(0)
  })

  it("covers exactly the five default-on events the backend notifies about", () => {
    expect(NOTIFIABLE_EVENTS.map((e) => e.type)).toEqual([
      "MATCH_STARTED",
      "GOAL",
      "CARD",
      "HALF_TIME",
      "MATCH_FINISHED",
    ])
  })
})

describe("season selector", () => {
  it("steps back one season in either label style", () => {
    expect(previousSeasonLabel("2026/27")).toBe("2025/26")
    expect(previousSeasonLabel("2000/01")).toBe("1999/00")
    expect(previousSeasonLabel("2026")).toBe("2025")
    expect(previousSeasonLabel("junk")).toBeNull()
    expect(previousSeasonLabel("")).toBeNull()
  })

  const info = (over: Partial<CompetitionSeasonsOut> = {}): CompetitionSeasonsOut => ({
    current: "2026/27",
    seasons: ["2026/27", "2025/26"],
    historical_supported: true,
    ...over,
  })

  it("lists stored seasons and, when history is supported, earlier requestable ones", () => {
    const options = selectableSeasons(info(), 2)
    expect(options).toEqual([
      { label: "2026/27", stored: true },
      { label: "2025/26", stored: true },
      { label: "2024/25", stored: false },
      { label: "2023/24", stored: false },
    ])
  })

  it("offers only stored seasons when the provider has no history", () => {
    expect(selectableSeasons(info({ historical_supported: false }))).toEqual([
      { label: "2026/27", stored: true },
      { label: "2025/26", stored: true },
    ])
  })

  it("offers nothing when no season is stored or info is missing", () => {
    expect(selectableSeasons(null)).toEqual([])
    expect(selectableSeasons(info({ seasons: [], current: null }))).toEqual([])
  })

  it("does not invent seasons from a label it can't step back from", () => {
    expect(selectableSeasons(info({ seasons: ["weird"] }), 3)).toEqual([{ label: "weird", stored: true }])
  })
})
