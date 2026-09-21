import { describe, expect, it } from "vitest"
import { applyRealtimeMessage, deriveBoardState, mergeById } from "./use-livescore-board"
import type { CompetitionOut, MatchSummary, RealtimeMessage, TeamOut } from "@/types/api"

const COMPETITION: CompetitionOut = { id: 1, name: "Premier League", country: "England", logo_url: null, type: "league" }
const HOME: TeamOut = { id: 1, name: "Arsenal", short_name: "ARS", country: "England", logo_url: null }
const AWAY: TeamOut = { id: 2, name: "Chelsea", short_name: "CHE", country: "England", logo_url: null }

function match(overrides: Partial<MatchSummary> = {}): MatchSummary {
  return {
    id: 1,
    competition: COMPETITION,
    home_team: HOME,
    away_team: AWAY,
    kickoff_time: "2026-09-21T19:00:00Z",
    status: "live",
    home_score: 1,
    away_score: 1,
    half_time_home_score: null,
    half_time_away_score: null,
    minute: 60,
    venue: null,
    last_synced_at: "2026-09-21T19:30:00Z",
    data_status: "FRESH",
    ...overrides,
  }
}

describe("mergeById", () => {
  it("dedupes the same match id appearing in multiple lists, keeping the last one", () => {
    const older = match({ id: 5, home_score: 0 })
    const newer = match({ id: 5, home_score: 1 })
    const map = mergeById([[older], [newer]])
    expect(map.get(5)).toEqual(newer)
  })

  it("keeps distinct matches from different lists", () => {
    const map = mergeById([[match({ id: 1 })], [match({ id: 2 })]])
    expect([...map.keys()].sort()).toEqual([1, 2])
  })
})

describe("applyRealtimeMessage", () => {
  it("updates score/status/minute for a known match", () => {
    const map = mergeById([[match({ id: 1, home_score: 1, away_score: 1, minute: 60 })]])
    const message: RealtimeMessage = {
      type: "GOAL",
      match: { id: "1", home_score: 2, away_score: 1, status: "live", minute: 62 },
    }

    const next = applyRealtimeMessage(map, message)

    expect(next.get(1)).toMatchObject({ home_score: 2, away_score: 1, minute: 62, data_status: "FRESH" })
  })

  it("leaves the map unchanged for a match id it doesn't know about", () => {
    const map = mergeById([[match({ id: 1 })]])
    const message: RealtimeMessage = {
      type: "MATCH_UPDATED",
      match: { id: "999", home_score: 0, away_score: 0, status: "live", minute: 1 },
    }

    const next = applyRealtimeMessage(map, message)

    expect(next).toBe(map) // unchanged reference -- no new match fabricated
    expect(next.has(999)).toBe(false)
  })

  it("does not mutate the original map (immutable update)", () => {
    const map = mergeById([[match({ id: 1, home_score: 1 })]])
    applyRealtimeMessage(map, {
      type: "GOAL",
      match: { id: "1", home_score: 5, away_score: 1, status: "live", minute: 70 },
    })

    expect(map.get(1)?.home_score).toBe(1) // original untouched
  })
})

describe("deriveBoardState", () => {
  const now = new Date("2026-09-21T20:00:00Z")

  it("classifies a live match into the live and today views", () => {
    const map = mergeById([[match({ id: 1, status: "live", kickoff_time: "2026-09-21T19:00:00Z" })]])
    const state = deriveBoardState(map, "open", now)

    expect(state.live.map((m) => m.id)).toEqual([1])
    expect(state.today.map((m) => m.id)).toEqual([1])
    expect(state.upcoming).toEqual([])
    expect(state.finished).toEqual([])
  })

  it("classifies a future scheduled match as upcoming, not live or today", () => {
    const map = mergeById([
      [match({ id: 2, status: "scheduled", kickoff_time: "2026-09-25T19:00:00Z" })],
    ])
    const state = deriveBoardState(map, "open", now)

    expect(state.upcoming.map((m) => m.id)).toEqual([2])
    expect(state.live).toEqual([])
    expect(state.today).toEqual([])
  })

  it("classifies a finished match that kicked off today as finished, not live", () => {
    const map = mergeById([
      [match({ id: 3, status: "finished", kickoff_time: "2026-09-21T10:00:00Z" })],
    ])
    const state = deriveBoardState(map, "open", now)

    expect(state.finished.map((m) => m.id)).toEqual([3])
    expect(state.live).toEqual([])
  })

  it("passes the connection status through unchanged", () => {
    const state = deriveBoardState(new Map(), "reconnecting", now)
    expect(state.connectionStatus).toBe("reconnecting")
  })
})
