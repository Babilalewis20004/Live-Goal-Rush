import { describe, expect, it } from "vitest"
import {
  barShare,
  describeEvent,
  describeFormResult,
  formSequenceLabel,
  formatAgo,
  formatStat,
  groupStandings,
  liveAnnouncement,
  minuteLabel,
  refreshPlanFor,
  relativeDayLabel,
  sortTimeline,
  statRows,
  statusDisplay,
  zoneTone,
} from "./match-centre"
import type {
  FormResultOut,
  MatchEventOut,
  MatchStatisticsOut,
  RealtimeMessage,
  TeamMatchStatsOut,
  TeamOut,
} from "@/types/api"

const HOME: TeamOut = { id: 1, name: "Arsenal", short_name: "ARS", country: null, logo_url: null }
const AWAY: TeamOut = { id: 2, name: "Chelsea", short_name: "CHE", country: null, logo_url: null }
const NOW = new Date("2026-10-01T12:00:00Z")

function event(overrides: Partial<MatchEventOut> = {}): MatchEventOut {
  return {
    id: 1,
    event_type: "goal",
    minute: 10,
    extra_minute: null,
    team: HOME,
    player: { id: 5, name: "Saka", position: null, photo_url: null },
    assist_player: null,
    description: null,
    ...overrides,
  }
}

function stats(team_id: number, overrides: Partial<TeamMatchStatsOut> = {}): TeamMatchStatsOut {
  return {
    team_id,
    possession: null,
    shots: null,
    shots_on_target: null,
    corners: null,
    fouls: null,
    offsides: null,
    yellow_cards: null,
    red_cards: null,
    pass_accuracy: null,
    expected_goals: null,
    ...overrides,
  }
}

describe("statusDisplay", () => {
  const base = { minute: null, kickoff_time: "2026-10-02T18:30:00Z" }

  it("LIVE with the elapsed minute", () => {
    expect(statusDisplay({ ...base, status: "live", minute: 67 }, NOW)).toEqual({
      kind: "live",
      label: "LIVE",
      detail: "67'",
      isLive: true,
      showScore: true,
    })
  })

  it("LIVE without a minute has no detail line rather than 'null''", () => {
    expect(statusDisplay({ ...base, status: "live" }, NOW).detail).toBeNull()
  })

  it("HALF TIME and FULL TIME", () => {
    expect(statusDisplay({ ...base, status: "halftime" }, NOW)).toMatchObject({ label: "HALF TIME", isLive: true })
    expect(statusDisplay({ ...base, status: "finished" }, NOW)).toMatchObject({
      label: "FULL TIME",
      isLive: false,
      showScore: true,
    })
  })

  it("upcoming shows the kickoff time and a relative day, and no score", () => {
    expect(statusDisplay({ ...base, status: "scheduled" }, NOW)).toEqual({
      kind: "upcoming",
      label: "18:30",
      detail: "Tomorrow",
      isLive: false,
      showScore: false,
    })
  })

  it("POSTPONED and CANCELLED hide the score", () => {
    expect(statusDisplay({ ...base, status: "postponed" }, NOW)).toMatchObject({ label: "POSTPONED", showScore: false })
    expect(statusDisplay({ ...base, status: "cancelled" }, NOW)).toMatchObject({ label: "CANCELLED", showScore: false })
  })
})

describe("relativeDayLabel", () => {
  it("names today / tomorrow / yesterday and otherwise gives a date (UTC)", () => {
    expect(relativeDayLabel("2026-10-01T23:30:00Z", NOW)).toBe("Today")
    expect(relativeDayLabel("2026-10-02T00:30:00Z", NOW)).toBe("Tomorrow")
    expect(relativeDayLabel("2026-09-30T18:00:00Z", NOW)).toBe("Yesterday")
    expect(relativeDayLabel("2026-10-10T18:00:00Z", NOW)).toBe("Sat 10 Oct")
  })
})

describe("timeline", () => {
  it("formats added time as 45+2'", () => {
    expect(minuteLabel(45, 2)).toBe("45+2'")
    expect(minuteLabel(67, null)).toBe("67'")
    expect(minuteLabel(90, 0)).toBe("90'")
  })

  it("orders 45' before 45+2' before 46', stable by id", () => {
    const sorted = sortTimeline([
      event({ id: 4, minute: 46 }),
      event({ id: 3, minute: 45, extra_minute: 2 }),
      event({ id: 2, minute: 45, extra_minute: null }),
      event({ id: 1, minute: 45, extra_minute: null }),
    ])
    expect(sorted.map((e) => e.id)).toEqual([1, 2, 3, 4])
  })

  it("does not mutate its input", () => {
    const input = [event({ id: 2, minute: 50 }), event({ id: 1, minute: 5 })]
    sortTimeline(input)
    expect(input.map((e) => e.id)).toEqual([2, 1])
  })

  it("a goal shows the scorer, the assist and which side it was", () => {
    const item = describeEvent(
      event({ assist_player: { id: 6, name: "Odegaard", position: null, photo_url: null } }),
      HOME.id,
      AWAY.id,
    )
    expect(item).toMatchObject({ icon: "goal", side: "home", title: "Saka", subtitle: "Assist: Odegaard", isGoal: true })
    expect(item.accessibleLabel).toBe("10' Goal by Saka for Arsenal")
  })

  it("an away event is placed on the away side", () => {
    expect(describeEvent(event({ team: AWAY }), HOME.id, AWAY.id).side).toBe("away")
  })

  it("a substitution reads 'off -> on' (player = on, assist_player = off)", () => {
    const item = describeEvent(
      event({
        event_type: "substitution",
        minute: 72,
        player: { id: 9, name: "Rodrygo", position: null, photo_url: null },
        assist_player: { id: 7, name: "Vinícius Jr.", position: null, photo_url: null },
      }),
      HOME.id,
      AWAY.id,
    )
    expect(item.title).toBe("Vinícius Jr. → Rodrygo")
    expect(item.icon).toBe("substitution")
    expect(item.isGoal).toBe(false)
    expect(item.accessibleLabel).toBe("72' Substitution for Arsenal: Rodrygo on, Vinícius Jr. off")
  })

  it("cards, second yellows, missed penalties, own goals and VAR each map to their own icon", () => {
    const icons = ["yellow_card", "second_yellow", "red_card", "penalty_missed", "own_goal", "penalty", "var"].map(
      (event_type) => describeEvent(event({ event_type }), HOME.id, AWAY.id).icon,
    )
    expect(icons).toEqual(["yellow_card", "second_yellow", "red_card", "penalty_missed", "own_goal", "penalty", "var"])
  })

  it("an unrecognised event type degrades to a generic entry instead of crashing", () => {
    const item = describeEvent(event({ event_type: "hologram" }), HOME.id, AWAY.id)
    expect(item.icon).toBe("other")
    expect(item.title).toBe("Saka")
  })

  it("uses provider event detail (and never invents one) for VAR", () => {
    expect(
      describeEvent(event({ event_type: "var", player: null, event_detail: "Goal disallowed" }), HOME.id, AWAY.id)
        .subtitle,
    ).toBe("Goal disallowed")
    expect(describeEvent(event({ event_type: "var", player: null }), HOME.id, AWAY.id).subtitle).toBeNull()
  })

  it("an own goal with no assist says so", () => {
    expect(describeEvent(event({ event_type: "own_goal" }), HOME.id, AWAY.id).subtitle).toBe("Own goal")
  })
})

describe("statistics rows", () => {
  it("returns nothing when no statistics were supplied", () => {
    expect(statRows(null)).toEqual([])
    expect(statRows({ home: null, away: null })).toEqual([])
  })

  it("omits a statistic the provider supplied for neither team (never a fake 0)", () => {
    const data: MatchStatisticsOut = {
      home: stats(1, { possession: 54, shots: 12 }),
      away: stats(2, { possession: 46, shots: 8 }),
    }
    expect(statRows(data).map((r) => r.key)).toEqual(["possession", "shots"])
  })

  it("keeps a row when only one side supplied the value, leaving the other as null", () => {
    const rows = statRows({ home: stats(1, { corners: 6 }), away: stats(2) })
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ key: "corners", home: 6, away: null })
    expect(formatStat(rows[0].away, rows[0].format)).toBe("–")
  })

  it("an explicit 0 is a real value and is kept", () => {
    const rows = statRows({ home: stats(1, { red_cards: 0 }), away: stats(2, { red_cards: 1 }) })
    expect(rows[0]).toMatchObject({ key: "red_cards", home: 0, away: 1 })
  })

  it("formats counts, percentages and xG", () => {
    expect(formatStat(54, "percent")).toBe("54%")
    expect(formatStat(12, "count")).toBe("12")
    expect(formatStat(1.456, "decimal")).toBe("1.46")
    expect(formatStat(null, "percent")).toBe("–")
  })

  it("bar share is proportional and 50/50 when both are zero or absent", () => {
    expect(barShare(54, 46)).toBeCloseTo(0.54)
    expect(barShare(0, 0)).toBe(0.5)
    expect(barShare(null, null)).toBe(0.5)
    expect(barShare(3, null)).toBe(1)
  })
})

describe("form", () => {
  const result: FormResultOut = {
    match_id: 1,
    result: "W",
    venue: "away",
    opponent: AWAY,
    goals_for: 2,
    goals_against: 1,
    kickoff_time: "2026-09-01T18:00:00Z",
    competition: { id: 1, name: "PL", country: null, logo_url: null, type: "league" },
  }

  it("describes a result for assistive tech", () => {
    expect(describeFormResult(result)).toBe("Win 2-1 away against Chelsea")
    expect(describeFormResult({ ...result, result: "L", venue: "home", goals_for: 0, goals_against: 3 })).toBe(
      "Loss 0-3 at home against Chelsea",
    )
  })

  it("labels the whole sequence oldest to newest", () => {
    expect(formSequenceLabel("WDL")).toBe("Last 3 results, oldest to newest: win, draw, loss")
    expect(formSequenceLabel("")).toBe("No recent results")
  })
})

describe("standings helpers", () => {
  it("styles provider classifications without deciding any rules", () => {
    expect(zoneTone("Champions League")).toBe("positive")
    expect(zoneTone("Promotion")).toBe("positive")
    expect(zoneTone("Europa League")).toBe("europe")
    expect(zoneTone("Relegation play-off")).toBe("negative")
    expect(zoneTone("Relegation")).toBe("negative")
    expect(zoneTone("Mid-table")).toBe("neutral")
    expect(zoneTone(null)).toBe("neutral")
  })

  it("groups a group-stage table and keeps a single table as one group", () => {
    const rows = [
      { group_name: "Group A", team: 1 },
      { group_name: "Group B", team: 2 },
      { group_name: "Group A", team: 3 },
    ]
    expect(groupStandings(rows).map((g) => [g.group, g.rows.map((r) => r.team)])).toEqual([
      ["Group A", [1, 3]],
      ["Group B", [2]],
    ])
    expect(groupStandings([{ group_name: "" }, { group_name: "" }])).toHaveLength(1)
  })
})

describe("real-time refresh plan", () => {
  const msg = (type: RealtimeMessage["type"], extra: Partial<RealtimeMessage["match"]> = {}): RealtimeMessage => ({
    type,
    match: { id: "1", home_score: 0, away_score: 0, status: "live", minute: 10, ...extra },
  })

  it("a lineup update or substitution refetches lineups only", () => {
    expect(refreshPlanFor(msg("LINEUP_UPDATED"))).toEqual({ lineups: true, statistics: false, standings: false })
    expect(refreshPlanFor(msg("SUBSTITUTION"))).toEqual({ lineups: true, statistics: false, standings: false })
  })

  it("full time refreshes lineups, standings and (if not already in the message) statistics", () => {
    expect(refreshPlanFor(msg("MATCH_FINISHED"))).toEqual({ lineups: true, statistics: true, standings: true })
    const withStats = msg("MATCH_FINISHED", { statistics: { home: null, away: null } })
    expect(refreshPlanFor(withStats).statistics).toBe(false)
  })

  it("goals, cards, minute ticks and statistics messages cause no extra requests", () => {
    for (const type of ["GOAL", "CARD", "MATCH_UPDATED", "HALF_TIME", "STATISTICS_UPDATED"] as const) {
      expect(refreshPlanFor(msg(type))).toEqual({ lineups: false, statistics: false, standings: false })
    }
  })
})

describe("liveAnnouncement (screen reader)", () => {
  const prev = { status: "live" as const, home_score: 1, away_score: 0 }
  const next = (over: object) => ({
    status: "live" as const,
    home_score: 1,
    away_score: 0,
    home_team: HOME,
    away_team: AWAY,
    ...over,
  })

  it("announces a goal with the new score", () => {
    expect(liveAnnouncement(prev, next({ home_score: 2 }))).toBe("Goal. Arsenal 2, Chelsea 0")
  })

  it("announces half time, full time and kick-off", () => {
    expect(liveAnnouncement(prev, next({ status: "halftime" }))).toBe("Half time. Arsenal 1, Chelsea 0")
    expect(liveAnnouncement(prev, next({ status: "finished" }))).toBe("Full time. Arsenal 1, Chelsea 0")
    expect(liveAnnouncement({ ...prev, status: "scheduled" }, next({}))).toBe("Kick-off. Arsenal 1, Chelsea 0")
  })

  it("stays silent for minute ticks and other unchanged updates", () => {
    expect(liveAnnouncement(prev, next({}))).toBeNull()
  })

  it("announces postponement/cancellation", () => {
    expect(liveAnnouncement(prev, next({ status: "postponed" }))).toBe("Match postponed")
    expect(liveAnnouncement(prev, next({ status: "cancelled" }))).toBe("Match cancelled")
  })
})

describe("formatAgo", () => {
  it("formats recent and older timestamps", () => {
    const at = (secondsAgo: number) => new Date(NOW.getTime() - secondsAgo * 1000).toISOString()
    expect(formatAgo(at(2), NOW)).toBe("just now")
    expect(formatAgo(at(24), NOW)).toBe("24 seconds ago")
    expect(formatAgo(at(60), NOW)).toBe("1 minute ago")
    expect(formatAgo(at(300), NOW)).toBe("5 minutes ago")
    expect(formatAgo(at(7200), NOW)).toBe("2 hours ago")
    expect(formatAgo(null, NOW)).toBeNull()
  })

  it("never goes negative for a clock-skewed future timestamp", () => {
    expect(formatAgo(new Date(NOW.getTime() + 10_000).toISOString(), NOW)).toBe("just now")
  })
})
