import { fireEvent, render, screen, waitFor } from "@testing-library/react-native"

import { AnalysisTab } from "@/components/analytics/analysis-tab"
import { ComparisonView } from "@/components/analytics/comparison-panel"
import { PlayerAnalyticsView } from "@/components/analytics/player-analytics"
import { PremiumGate } from "@/components/analytics/premium-gate"
import { PredictionView } from "@/components/analytics/prediction-card"
import { TeamAnalytics, TeamAnalyticsView } from "@/components/analytics/team-analytics"
import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import type { MatchComparisonOut, MatchDetail, PlayerAnalyticsOut, PredictionOut, TeamAnalyticsOut } from "@/types/api"

jest.mock("@/hooks/use-auth", () => ({ useAuth: jest.fn() }))
jest.mock("@/lib/api", () => {
  class ApiError extends Error {
    status: number
    entitlement?: string
    constructor(status: number, message: string, entitlement?: string) {
      super(message)
      this.status = status
      this.entitlement = entitlement
    }
  }
  return {
    ApiError,
    api: {
      getTeamAnalytics: jest.fn(),
      getMatchPrediction: jest.fn(),
      getMatchComparison: jest.fn(),
      getMatchInsightRecords: jest.fn(),
      getMatchHeadToHead: jest.fn(),
      getExtendedHeadToHead: jest.fn(),
      getAdPlacements: jest.fn(),
    },
  }
})

const mockApi = api as unknown as Record<string, jest.Mock>
const mockUseAuth = useAuth as jest.Mock

beforeEach(() => {
  for (const fn of Object.values(mockApi)) fn.mockReset()
  mockUseAuth.mockReturnValue({ user: { id: 1, role: "user" }, loading: false })
  mockApi.getAdPlacements.mockResolvedValue([])
})

const prediction = (over: Partial<PredictionOut> = {}): PredictionOut => ({
  match_id: 1, status: "available", label: "Model estimate", disclaimer: "A statistical estimate from past results, not a guarantee and not betting advice.",
  model_version: "poisson-v1", generated_at: "2026-10-08T10:00:00Z", data_timestamp: null, confidence: "medium", confidence_score: null,
  home_win: 0.48, draw: 0.27, away_win: 0.25, expected_total_goals: 2.6, expected_home_goals: null, expected_away_goals: null,
  influences: ["Recent results of both teams"], factors: null, locked: ["expected_goals_by_team"], reason: null, ...over,
})

describe("PredictionView", () => {
  it("is labelled as an estimate with percentages that add to 100 and the caveat", async () => {
    await render(<PredictionView prediction={prediction()} homeName="Reds" awayName="Blues" signedIn />)
    expect(screen.getByText("Model estimate")).toBeTruthy()
    expect(screen.getByText("Statistical prediction")).toBeTruthy()
    expect(screen.getByLabelText("Reds 48 percent")).toBeTruthy()
    expect(screen.getByLabelText("Draw 27 percent")).toBeTruthy()
    expect(screen.getByLabelText("Blues 25 percent")).toBeTruthy()
    expect(screen.getByText("Prediction influenced by")).toBeTruthy()
    expect(screen.getByText(/not a guarantee and not betting advice/)).toBeTruthy()
    expect(screen.getByText(/model poisson-v1/)).toBeTruthy()
    expect(screen.getByRole("link", { name: "See Premium" })).toBeTruthy() // locked breakdown points to Premium
  })

  it("states plainly when there is no estimate", async () => {
    await render(<PredictionView prediction={prediction({ status: "insufficient_data", home_win: null, draw: null, away_win: null, reason: "Not enough past results for both teams to make an estimate." })} homeName="A" awayName="B" signedIn={false} />)
    expect(screen.getByText(/Not enough past results/)).toBeTruthy()
    expect(screen.queryByText(/%/)).toBeNull()
  })
})

const comparison = (): MatchComparisonOut => ({
  match_id: 1,
  home_team: { id: 1, name: "Reds" } as MatchComparisonOut["home_team"], away_team: { id: 2, name: "Blues" } as MatchComparisonOut["away_team"],
  generated_at: "2026-10-08T10:00:00Z", tier: "basic", form_window: 5, home_form: null, away_form: null, home_sequence: "", away_sequence: "", head_to_head: null,
  rows: [
    { key: "goals_for", label: "Goals scored per match", home: 2.2, away: 1, higher_is_better: true, home_sample: 5, away_sample: 5, premium: false },
    { key: "possession", label: "Possession %", home: 61, away: null, higher_is_better: null, home_sample: 4, away_sample: 0, premium: true },
  ],
  locked: ["possession"], limitations: ["Only 3 of the last 5 matches are stored."],
})

describe("ComparisonView", () => {
  it("speaks each row, shows a dash for missing data and lists limitations", async () => {
    await render(<ComparisonView data={comparison()} signedIn={false} />)
    expect(screen.getByLabelText("Goals scored per match: Reds 2.2, Blues 1; Reds ahead")).toBeTruthy()
    expect(screen.getByLabelText("Possession %: Reds 61, Blues —")).toBeTruthy()
    expect(screen.getByText("Not enough data for one side.")).toBeTruthy()
    expect(screen.getByText("Note: Only 3 of the last 5 matches are stored.")).toBeTruthy()
    expect(screen.getByRole("link", { name: "Sign in to see Premium" })).toBeTruthy()
  })
})

const team = (over: Partial<TeamAnalyticsOut> = {}): TeamAnalyticsOut => ({
  team_id: 1, team_name: "Reds", scope: "overall", window: 10, matches_considered: 6, data_timestamp: null, generated_at: "2026-10-08T10:00:00Z", tier: "full",
  record: { played: 6, wins: 3, draws: 2, losses: 1, points: 11, points_per_match: 1.83 },
  attack: { goals: { value: 7, sample: 6 }, shots: { value: 54, sample: 4 }, expected_goals: { value: null, sample: 0 } },
  possession: {}, defence: { clean_sheets: { value: 3, sample: 6 } }, discipline: {}, unavailable: ["progressive_passes"], locked: [], limitations: ["Match statistics exist for 4 of 6 matches; per-metric samples are shown."], ...over,
})

describe("TeamAnalyticsView", () => {
  it("reports coverage and never shows missing data as zero", async () => {
    await render(<TeamAnalyticsView data={team()} signedIn />)
    expect(screen.getByLabelText("Shots: 54, 4 of 6 matches")).toBeTruthy()
    expect(screen.getByLabelText("Expected goals (xG): not provided by the data source")).toBeTruthy()
    expect(screen.getByText(/Not tracked by this platform: progressive passes/)).toBeTruthy()
    expect(screen.getByText(/Match statistics exist for 4 of 6/)).toBeTruthy()
  })
})

describe("TeamAnalytics (screen section)", () => {
  it("explains a refused longer window with the Premium gate instead of an error", async () => {
    const { ApiError } = jest.requireMock("@/lib/api")
    mockApi.getTeamAnalytics.mockImplementation(async (_id: number, opts: { window?: number }) => {
      if ((opts.window ?? 10) > 10) throw new ApiError(402, "Extended history is a Premium feature.", "extended_history")
      return team()
    })
    await render(<TeamAnalytics teamId={1} />)
    expect(await screen.findByText(/Record · last 6 matches/)).toBeTruthy()
    await fireEvent.press(screen.getByRole("button", { name: "Last 20 🔒" }))
    expect(await screen.findByText(/Longer history is a Premium feature|Longer history/)).toBeTruthy()
    expect(screen.getByLabelText("Longer history is a Premium feature")).toBeTruthy()
    expect(mockApi.getTeamAnalytics).toHaveBeenLastCalledWith(1, { scope: "overall", window: 20 })
  })
})

describe("PlayerAnalyticsView", () => {
  const base: PlayerAnalyticsOut = {
    player_id: 1, player_name: "Sam", generated_at: "2026-10-08T10:00:00Z", tier: "full", seasons: [], window: 10, matches_with_statistics: 3,
    totals: { goals: { value: 3, sample: 3 }, minutes_played: { value: 260, sample: 3 } }, per_90: { goals: { value: 1.04, sample: 3 } },
    recent: [{ match_id: 1, kickoff_time: "2026-09-01T00:00:00Z", opponent: "Greens", minutes: 90, goals: 1, assists: null, shots: 4, shots_on_target: null, key_passes: 2, tackles: null, yellow_cards: null, red_cards: null }],
    form_goal_involvements: [1, 1, 2], unavailable: ["expected_goals"], locked: [], limitations: [],
  }

  it("describes the chart in words and keeps missing values as dashes", async () => {
    await render(<PlayerAnalyticsView data={base} signedIn />)
    expect(screen.getByLabelText("Goal involvements in the last 3 matches, oldest to newest: 1, 1, 2")).toBeTruthy()
    expect(screen.getByLabelText("Against Greens: 90 minutes, 1 goals, — assists")).toBeTruthy()
    expect(screen.getByText(/Not tracked by this platform: expected goals/)).toBeTruthy()
  })

  it("shows a basic caller only the free history", async () => {
    const basic = { ...base, tier: "basic" as const, matches_with_statistics: 0, totals: {}, per_90: {}, recent: [], form_goal_involvements: [], locked: ["recent_matches"],
      seasons: [{ competition_id: 1, competition_name: "League", season: "2025/26", appearances: 20, goals: 9, assists: 4 }] }
    await render(<PlayerAnalyticsView data={basic} signedIn={false} />)
    expect(screen.getByText(/2025\/26 · League/)).toBeTruthy()
    expect(screen.queryByText("Per 90 minutes")).toBeNull()
    expect(screen.getByRole("link", { name: "Sign in to see Premium" })).toBeTruthy()
  })
})

describe("PremiumGate", () => {
  it("says what Premium adds, that the basics stay free, and where to go", async () => {
    await render(<PremiumGate title="Longer history" items={["Last 20 matches"]} signedIn />)
    expect(screen.getByText(/stay free/)).toBeTruthy()
    expect(screen.getByRole("link", { name: "See Premium" })).toBeTruthy()
  })
})

describe("AnalysisTab", () => {
  const match = { id: 1, status: "scheduled", home_team: { id: 1, name: "Reds" }, away_team: { id: 2, name: "Blues" } } as unknown as MatchDetail

  it("loads the estimate, comparison and insights, and gates longer head-to-head history", async () => {
    const { ApiError } = jest.requireMock("@/lib/api")
    mockApi.getMatchPrediction.mockResolvedValue(prediction())
    mockApi.getMatchComparison.mockResolvedValue(comparison())
    mockApi.getMatchInsightRecords.mockResolvedValue([
      { entity_type: "match", entity_id: 1, insight_type: "live:live_shots", text: "Reds have had 11 shots to Blues's 3.", value: 8, source_data_version: "v", generated_at: "2026-10-08T10:00:00Z" },
    ])
    mockApi.getMatchHeadToHead.mockResolvedValue({ meetings: [], total_meetings: 3, home_team_wins: 2, draws: 1, away_team_wins: 0, average_goals: 2.3, home_team_goals: 5, away_team_goals: 2, recent_form: "WDW", limitation: null })
    mockApi.getExtendedHeadToHead.mockRejectedValue(new ApiError(402, "Extended history is a Premium feature.", "extended_history"))

    await render(<AnalysisTab match={match} nudges={{}} />)
    expect(await screen.findByText("Model estimate")).toBeTruthy()
    expect(await screen.findByText("Team comparison")).toBeTruthy()
    expect(await screen.findByLabelText("Live. Reds have had 11 shots to Blues's 3.")).toBeTruthy()
    expect(await screen.findByText(/3 meetings: Reds 2 wins, 1 draws, Blues 0 wins/)).toBeTruthy()

    await fireEvent.press(screen.getByRole("button", { name: "All meetings 🔒" }))
    await waitFor(() => expect(mockApi.getExtendedHeadToHead).toHaveBeenCalledWith(1, "all"))
    expect(await screen.findByLabelText("Longer head-to-head history is a Premium feature")).toBeTruthy()
  })

  it("refetches the estimate when the server nudges prediction.updated", async () => {
    mockApi.getMatchPrediction.mockResolvedValue(prediction())
    mockApi.getMatchComparison.mockResolvedValue(comparison())
    mockApi.getMatchInsightRecords.mockResolvedValue([])
    mockApi.getMatchHeadToHead.mockResolvedValue({ meetings: [], total_meetings: 0, home_team_wins: 0, draws: 0, away_team_wins: 0 })
    const { rerender } = await render(<AnalysisTab match={match} nudges={{}} />)
    await screen.findByText("Model estimate")
    const before = mockApi.getMatchPrediction.mock.calls.length
    await rerender(<AnalysisTab match={match} nudges={{ "prediction.updated": 1 }} />)
    await waitFor(() => expect(mockApi.getMatchPrediction.mock.calls.length).toBeGreaterThan(before))
  })
})
