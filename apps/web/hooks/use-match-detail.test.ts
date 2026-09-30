import { describe, expect, it } from "vitest"
import { applyRealtimeMessage } from "./use-match-detail"
import type { CompetitionOut, MatchDetail, RealtimeMessage, TeamOut } from "@/types/api"

const COMPETITION: CompetitionOut = { id: 1, name: "Premier League", country: "England", logo_url: null, type: "league" }
const HOME: TeamOut = { id: 1, name: "Arsenal", short_name: "ARS", country: "England", logo_url: null }
const AWAY: TeamOut = { id: 2, name: "Chelsea", short_name: "CHE", country: "England", logo_url: null }

function detail(overrides: Partial<MatchDetail> = {}): MatchDetail {
  return {
    id: 1,
    competition: COMPETITION,
    home_team: HOME,
    away_team: AWAY,
    kickoff_time: "2026-09-21T19:00:00Z",
    status: "live",
    home_score: 1,
    away_score: 0,
    half_time_home_score: null,
    half_time_away_score: null,
    minute: 40,
    venue: null,
    last_synced_at: "2026-09-21T19:40:00Z",
    data_status: "FRESH",
    events: [],
    ...overrides,
  }
}

describe("applyRealtimeMessage (match detail)", () => {
  it("ignores a message for a different match id", () => {
    const match = detail({ id: 1 })
    const message: RealtimeMessage = {
      type: "GOAL",
      match: { id: "2", home_score: 9, away_score: 9, status: "live", minute: 1 },
    }

    expect(applyRealtimeMessage(match, message)).toBe(match)
  })

  it("updates score/status/minute for this match", () => {
    const match = detail({ id: 1, home_score: 1, away_score: 0 })
    const message: RealtimeMessage = {
      type: "GOAL",
      match: { id: "1", home_score: 2, away_score: 0, status: "live", minute: 55 },
    }

    const next = applyRealtimeMessage(match, message)
    expect(next).toMatchObject({ home_score: 2, minute: 55, data_status: "FRESH" })
  })

  it("appends a new event carried in the message, resolving the team by id", () => {
    const match = detail({ id: 1, events: [] })
    const message: RealtimeMessage = {
      type: "GOAL",
      match: {
        id: "1",
        home_score: 1,
        away_score: 0,
        status: "live",
        minute: 12,
        event: { id: 100, event_type: "goal", minute: 12, team_id: 1, player: "Saka", description: null },
      },
    }

    const next = applyRealtimeMessage(match, message)

    expect(next.events).toHaveLength(1)
    expect(next.events[0]).toMatchObject({ id: 100, event_type: "goal", minute: 12 })
    expect(next.events[0].team).toEqual(HOME)
    expect(next.events[0].player?.name).toBe("Saka")
  })

  it("does not duplicate an event whose id already exists in the timeline", () => {
    const existingEvent = {
      id: 100,
      event_type: "goal",
      minute: 12,
      extra_minute: null,
      team: HOME,
      player: null,
      assist_player: null,
      description: null,
    }
    const match = detail({ id: 1, events: [existingEvent] })
    const message: RealtimeMessage = {
      type: "GOAL",
      match: {
        id: "1",
        home_score: 1,
        away_score: 0,
        status: "live",
        minute: 12,
        event: { id: 100, event_type: "goal", minute: 12, team_id: 1, player: null, description: null },
      },
    }

    const next = applyRealtimeMessage(match, message)
    expect(next.events).toHaveLength(1)
  })

  it("keeps the event timeline sorted by minute after inserting", () => {
    const late = {
      id: 1,
      event_type: "goal",
      minute: 80,
      extra_minute: null,
      team: HOME,
      player: null,
      assist_player: null,
      description: null,
    }
    const match = detail({ id: 1, events: [late] })
    const message: RealtimeMessage = {
      type: "GOAL",
      match: {
        id: "1",
        home_score: 2,
        away_score: 0,
        status: "live",
        minute: 20,
        event: { id: 2, event_type: "goal", minute: 20, team_id: 1, player: null, description: null },
      },
    }

    const next = applyRealtimeMessage(match, message)
    expect(next.events.map((e) => e.minute)).toEqual([20, 80])
  })
})

describe("applyRealtimeMessage (Phase 4 payload fields)", () => {
  it("keeps added time and orders it after the regular minute", () => {
    const match = detail({
      id: 1,
      events: [
        {
          id: 1,
          event_type: "yellow_card",
          minute: 45,
          extra_minute: null,
          team: HOME,
          player: null,
          assist_player: null,
          description: null,
        },
      ],
    })
    const message: RealtimeMessage = {
      type: "CARD",
      match: {
        id: "1",
        home_score: 1,
        away_score: 0,
        status: "live",
        minute: 47,
        event: {
          id: 2,
          event_type: "yellow_card",
          minute: 45,
          extra_minute: 2,
          team_id: 2,
          player: "Caicedo",
          description: null,
        },
      },
    }
    const next = applyRealtimeMessage(match, message)
    expect(next.events.map((e) => [e.id, e.minute, e.extra_minute])).toEqual([
      [1, 45, null],
      [2, 45, 2],
    ])
  })

  it("a substitution carries who went off as assist_player", () => {
    const message: RealtimeMessage = {
      type: "SUBSTITUTION",
      match: {
        id: "1",
        home_score: 1,
        away_score: 0,
        status: "live",
        minute: 60,
        event: {
          id: 9,
          event_type: "substitution",
          minute: 60,
          team_id: 1,
          player: "Rodrygo",
          assist: "Vinícius Jr.",
          description: null,
          event_detail: "Tactical",
        },
      },
    }
    const [added] = applyRealtimeMessage(detail({ id: 1 }), message).events
    expect(added.player?.name).toBe("Rodrygo")
    expect(added.assist_player?.name).toBe("Vinícius Jr.")
    expect(added.event_detail).toBe("Tactical")
  })

  it("a statistics-only message still updates score/status/minute and adds no event", () => {
    const message: RealtimeMessage = {
      type: "STATISTICS_UPDATED",
      match: {
        id: "1",
        home_score: 1,
        away_score: 0,
        status: "live",
        minute: 41,
        statistics: { home: null, away: null },
      },
    }
    const next = applyRealtimeMessage(detail({ id: 1, minute: 40 }), message)
    expect(next.minute).toBe(41)
    expect(next.events).toEqual([])
  })
})
