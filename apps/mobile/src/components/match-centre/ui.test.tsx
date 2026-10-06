import { act, fireEvent, render, screen } from "@testing-library/react-native"

import { FeatureState, FormStrip, StaleBanner, TabBar } from "@/components/match-centre/ui"
import type { Capabilities, TeamFormOut, TeamOut } from "@/types/api"

const OPPONENT: TeamOut = { id: 2, name: "Chelsea", short_name: "CHE", country: null, logo_url: null }
const COMPETITION = { id: 1, name: "PL", country: null, logo_url: null, type: "league" }

const CAPABILITIES: Capabilities = {
  match_events: true,
  lineups: false,
  match_statistics: true,
  player_statistics: false,
  team_squads: true,
  player_profiles: true,
  standings: true,
  top_scorers: true,
  venues: true,
  historical_seasons: true,
  head_to_head: true,
  form: true,
}

describe("TabBar", () => {
  const tabs = [
    { id: "a", label: "Overview" },
    { id: "b", label: "Stats" },
  ]

  it("renders every tab with its selected state exposed to assistive tech", async () => {
    await render(<TabBar tabs={tabs} active="b" onChange={() => {}} />)
    expect(screen.getByRole("tab", { name: "Stats", selected: true })).toBeTruthy()
    expect(screen.getByRole("tab", { name: "Overview", selected: false })).toBeTruthy()
  })

  it("reports the tapped tab", async () => {
    const onChange = jest.fn()
    await render(<TabBar tabs={tabs} active="a" onChange={onChange} />)
    await fireEvent.press(screen.getByRole("tab", { name: "Stats" }))
    expect(onChange).toHaveBeenCalledWith("b")
  })
})

describe("FeatureState", () => {
  it("says 'not available' when the provider never supplies the feature", async () => {
    await render(<FeatureState feature="lineups" capabilities={CAPABILITIES} pendingMessage="Check back soon" />)
    expect(screen.getByText("Not available")).toBeTruthy()
    expect(screen.getByText(/aren't provided by the current football data provider/)).toBeTruthy()
    expect(screen.queryByText("Check back soon")).toBeNull()
  })

  it("shows the pending message when the feature is supported but there's no data yet", async () => {
    await render(<FeatureState feature="match_statistics" capabilities={CAPABILITIES} pendingMessage="Check back soon" />)
    expect(screen.getByText("Check back soon")).toBeTruthy()
    expect(screen.queryByText("Not available")).toBeNull()
  })

  it("treats unknown capabilities as 'pending', never as 'unsupported'", async () => {
    await render(<FeatureState feature="lineups" capabilities={null} pendingMessage="Check back soon" />)
    expect(screen.getByText("Check back soon")).toBeTruthy()
  })
})

describe("StaleBanner", () => {
  beforeEach(() => {
    jest.useFakeTimers()
    jest.setSystemTime(new Date("2026-10-01T12:00:30Z"))
  })
  afterEach(() => jest.useRealTimers())

  const lastUpdated = "2026-10-01T12:00:06Z" // 24 s before "now"

  it("is hidden while the connection is open or connecting", async () => {
    const { rerender } = await render(<StaleBanner status="open" isLive lastUpdatedAt={lastUpdated} />)
    expect(screen.queryByText("Connection lost")).toBeNull()
    await rerender(<StaleBanner status="connecting" isLive lastUpdatedAt={lastUpdated} />)
    expect(screen.queryByText("Connection lost")).toBeNull()
  })

  it("is hidden for matches that aren't live, even when disconnected", async () => {
    await render(<StaleBanner status="closed" isLive={false} lastUpdatedAt={lastUpdated} />)
    expect(screen.queryByText("Connection lost")).toBeNull()
  })

  it("shows the last known state and how old it is when a live match loses its connection", async () => {
    await render(<StaleBanner status="reconnecting" isLive lastUpdatedAt={lastUpdated} />)
    expect(screen.getByRole("alert")).toBeTruthy()
    expect(screen.getByText("Connection lost")).toBeTruthy()
    expect(screen.getByText(/Showing last known match state/)).toBeTruthy()
    expect(screen.getByText(/Updated 24 seconds ago/)).toBeTruthy()
  })

  it("keeps the age current as time passes", async () => {
    await render(<StaleBanner status="closed" isLive lastUpdatedAt={lastUpdated} />)
    await act(async () => {
      jest.advanceTimersByTime(35_000) // the banner re-renders on its own 5 s tick
    })
    expect(screen.getByText(/Updated 59 seconds ago|Updated 1 minute ago/)).toBeTruthy()
  })
})

describe("FormStrip", () => {
  const form = (sequence: string): TeamFormOut => ({
    team_id: 1,
    scope: "overall",
    limit: 5,
    sequence,
    results: [...sequence].reverse().map((r, i) => ({
      match_id: i + 1,
      result: r as "W" | "D" | "L",
      venue: "home" as const,
      opponent: OPPONENT,
      goals_for: r === "W" ? 2 : r === "D" ? 1 : 0,
      goals_against: r === "W" ? 0 : 1,
      kickoff_time: "2026-09-01T18:00:00Z",
      competition: COMPETITION,
    })),
  })

  it("draws results oldest to newest with a spoken label per chip", async () => {
    await render(<FormStrip form={form("WDL")} title="Arsenal" />)
    expect(screen.getByLabelText("Last 3 results, oldest to newest: win, draw, loss")).toBeTruthy()
    expect(screen.getByLabelText("Win 2-0 at home against Chelsea")).toBeTruthy()
    expect(screen.getByLabelText("Loss 0-1 at home against Chelsea")).toBeTruthy()
  })

  it("says so when there are no stored results instead of inventing a streak", async () => {
    await render(<FormStrip form={form("")} title="Brighton" />)
    expect(screen.getByText("No recent results stored.")).toBeTruthy()
  })
})
