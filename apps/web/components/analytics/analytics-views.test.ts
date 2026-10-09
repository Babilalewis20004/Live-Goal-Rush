// @vitest-environment node
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ComparisonView } from "@/components/analytics/comparison-panel"
import { PlayerAnalyticsView } from "@/components/analytics/player-analytics"
import { LockedNote, PremiumGate } from "@/components/analytics/premium-gate"
import { PredictionView } from "@/components/analytics/prediction-card"
import { TeamAnalyticsView } from "@/components/analytics/team-analytics"
import type { MatchComparisonOut, PlayerAnalyticsOut, PredictionOut, TeamAnalyticsOut } from "@/types/api"

const html = (node: Parameters<typeof renderToStaticMarkup>[0]) => renderToStaticMarkup(node)

const prediction = (over: Partial<PredictionOut> = {}): PredictionOut => ({
  match_id: 1, status: "available", label: "Model estimate", disclaimer: "A statistical estimate from past results, not a guarantee and not betting advice.",
  model_version: "poisson-v1", generated_at: "2026-10-08T10:00:00Z", data_timestamp: "2026-10-01T00:00:00Z", confidence: "medium", confidence_score: null,
  home_win: 0.48, draw: 0.27, away_win: 0.25, expected_total_goals: 2.6, expected_home_goals: null, expected_away_goals: null,
  influences: ["Recent results of both teams", "Goals scored and conceded compared with the league average"], factors: null,
  locked: ["expected_goals_by_team", "model_factors"], reason: null, ...over,
})

describe("PredictionView", () => {
  it("labels the estimate, shows whole-number percentages summing to 100, and never calls it a certainty", () => {
    const out = html(createElement(PredictionView, { prediction: prediction(), homeName: "Reds", awayName: "Blues", signedIn: false }))
    expect(out).toContain("Model estimate")
    expect(out).toContain("Statistical prediction")
    expect(out).toContain("48%")
    expect(out).toContain("27%")
    expect(out).toContain("25%")
    expect(out).toContain("Prediction influenced by")
    expect(out).toContain("not a guarantee and not betting advice")
    expect(out).toContain("model poisson-v1")
    expect(out).not.toMatch(/will win|guaranteed|sure thing|odds|bet on/i)
    expect(out).toContain('aria-label="Reds 48%, Draw 27%, Blues 25%"') // the bar is described in words
  })

  it("keeps the Premium breakdown out for a free viewer and points to Premium", () => {
    const out = html(createElement(PredictionView, { prediction: prediction(), homeName: "Reds", awayName: "Blues", signedIn: true }))
    expect(out).not.toContain("Reds 1.") // no per-team expected goals
    expect(out).toContain("/premium")
  })

  it("shows the per-team breakdown when the server provided it", () => {
    const out = html(createElement(PredictionView, {
      prediction: prediction({ expected_home_goals: 1.8, expected_away_goals: 0.8, locked: [] }), homeName: "Reds", awayName: "Blues", signedIn: true,
    }))
    expect(out).toContain("Reds 1.8")
    expect(out).toContain("Blues 0.8")
    expect(out).not.toContain("/premium")
  })

  it("explains an unavailable estimate instead of inventing one", () => {
    const out = html(createElement(PredictionView, {
      prediction: prediction({ status: "insufficient_data", home_win: null, draw: null, away_win: null, expected_total_goals: null, reason: "Not enough past results for both teams to make an estimate." }),
      homeName: "Reds", awayName: "Blues", signedIn: false,
    }))
    expect(out).toContain("Not enough past results")
    expect(out).not.toContain("%")
  })
})

const comparison = (over: Partial<MatchComparisonOut> = {}): MatchComparisonOut => ({
  match_id: 1,
  home_team: { id: 1, name: "Reds", short_name: null, country: null, logo_url: null, venue: null } as MatchComparisonOut["home_team"],
  away_team: { id: 2, name: "Blues", short_name: null, country: null, logo_url: null, venue: null } as MatchComparisonOut["away_team"],
  generated_at: "2026-10-08T10:00:00Z", tier: "basic", form_window: 5, home_form: null, away_form: null, home_sequence: "WDLWW", away_sequence: "",
  head_to_head: null,
  rows: [
    { key: "goals_for", label: "Goals scored per match", home: 2.2, away: 1, higher_is_better: true, home_sample: 5, away_sample: 5, premium: false },
    { key: "possession", label: "Possession %", home: 61, away: null, higher_is_better: null, home_sample: 4, away_sample: 0, premium: true },
  ],
  locked: ["possession", "shots"], limitations: ["Only 3 of the last 5 matches are stored."], ...over,
})

describe("ComparisonView", () => {
  it("never relies on colour or bars alone: every row has numbers and a spoken summary", () => {
    const out = html(createElement(ComparisonView, { data: comparison(), signedIn: false }))
    expect(out).toContain('aria-label="Goals scored per match: Reds 2.2, Blues 1; Reds ahead"')
    expect(out).toContain("Last 5 matches before kick-off")
    expect(out).toContain("—") // the missing side is a dash, not 0
    expect(out).toContain("Not enough data for one side.")
    expect(out).toContain("Only 3 of the last 5 matches are stored.")
    expect(out).toContain("/login?next=/premium")
  })
})

const team = (over: Partial<TeamAnalyticsOut> = {}): TeamAnalyticsOut => ({
  team_id: 1, team_name: "Reds", scope: "overall", window: 10, matches_considered: 6, data_timestamp: null, generated_at: "2026-10-08T10:00:00Z", tier: "full",
  record: { played: 6, wins: 3, draws: 2, losses: 1, points: 11, points_per_match: 1.83 },
  attack: { goals: { value: 7, sample: 6 }, shots: { value: 54, sample: 4 }, expected_goals: { value: null, sample: 0 } },
  possession: {}, defence: { clean_sheets: { value: 3, sample: 6 } }, discipline: {}, unavailable: ["progressive_passes"], locked: [], limitations: ["Match statistics exist for 4 of 6 matches; per-metric samples are shown."], ...over,
})

describe("TeamAnalyticsView", () => {
  it("shows partial coverage and treats a missing statistic as 'not provided', not zero", () => {
    const out = html(createElement(TeamAnalyticsView, { data: team(), signedIn: true }))
    expect(out).toContain("4 of 6 matches")
    expect(out).toContain("(not provided by the data source)")
    expect(out).toContain("Not tracked by this platform: progressive passes.")
    expect(out).toContain("Match statistics exist for 4 of 6 matches")
    expect(out).toContain("<strong") // record
  })

  it("offers the upgrade for a basic view", () => {
    const out = html(createElement(TeamAnalyticsView, { data: team({ tier: "basic", locked: ["possession", "discipline"] }), signedIn: true }))
    expect(out).toContain("/premium")
    expect(out).toContain("possession, discipline")
  })
})

describe("PlayerAnalyticsView", () => {
  const base: PlayerAnalyticsOut = {
    player_id: 1, player_name: "Sam", generated_at: "2026-10-08T10:00:00Z", tier: "full", seasons: [], window: 10, matches_with_statistics: 3,
    totals: { goals: { value: 3, sample: 3 }, minutes_played: { value: 260, sample: 3 } }, per_90: { goals: { value: 1.04, sample: 3 } },
    recent: [{ match_id: 1, kickoff_time: "2026-09-01T00:00:00Z", opponent: "Greens", minutes: 90, goals: 1, assists: null, shots: 4, shots_on_target: null, key_passes: 2, tackles: null, yellow_cards: null, red_cards: null }],
    form_goal_involvements: [1, 1, 2], unavailable: ["expected_goals"], locked: [], limitations: [],
  }

  it("gives the trend chart a text alternative and keeps missing values as dashes", () => {
    const out = html(createElement(PlayerAnalyticsView, { data: base, signedIn: true }))
    expect(out).toContain("Goal involvements in the last 3 matches, oldest to newest: 1, 1, 2")
    expect(out).toContain("Greens")
    expect(out).toContain("—")
    expect(out).toContain("Not tracked by this platform: expected goals.")
    expect(out).toContain("<caption")
  })

  it("shows only the free history to a basic caller", () => {
    const basic: PlayerAnalyticsOut = { ...base, tier: "basic", matches_with_statistics: 0, totals: {}, per_90: {}, recent: [], form_goal_involvements: [], locked: ["recent_matches", "per_90"],
      seasons: [{ competition_id: 1, competition_name: "League", season: "2025/26", appearances: 20, goals: 9, assists: 4 }] }
    const out = html(createElement(PlayerAnalyticsView, { data: basic, signedIn: false }))
    expect(out).toContain("League")
    expect(out).not.toContain("Per 90 minutes")
    expect(out).toContain("recent matches, per 90")
    expect(out).toContain("/login?next=/premium")
  })
})

describe("gates", () => {
  it("explains what Premium adds and that the basics stay free", () => {
    const out = html(createElement(PremiumGate, { title: "Longer history", items: ["Last 20 matches"], signedIn: true }))
    expect(out).toContain("Longer history is a Premium feature")
    expect(out).toContain("stay free")
    expect(out).toContain('href="/premium"')
  })

  it("renders nothing when there is nothing locked", () => {
    expect(html(createElement(LockedNote, { locked: [], signedIn: true }))).toBe("")
  })
})
