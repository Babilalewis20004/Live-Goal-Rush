import { render, screen } from "@testing-library/react-native"

import {
  HeadToHeadSection,
  LineupPlayerRow,
  MatchHeader,
  StandingRowView,
  StandingsLegend,
  StatRowView,
  TimelineRow,
  buildTimeline,
} from "@/components/match-centre/rows"
import { statRows } from "@/lib/match-centre"
import type { HeadToHeadOut, MatchDetail, MatchEventOut, StandingEntry, TeamOut } from "@/types/api"

const HOME: TeamOut = { id: 1, name: "Arsenal", short_name: "ARS", country: null, logo_url: null }
const AWAY: TeamOut = { id: 2, name: "Chelsea", short_name: "CHE", country: null, logo_url: null }

function match(over: Partial<MatchDetail> = {}): MatchDetail {
  return {
    id: 7,
    competition: { id: 1, name: "Premier League", country: null, logo_url: null, type: "league" },
    home_team: HOME,
    away_team: AWAY,
    kickoff_time: "2099-01-02T18:30:00Z",
    status: "live",
    home_score: 2,
    away_score: 1,
    half_time_home_score: null,
    half_time_away_score: null,
    minute: 67,
    venue: "Emirates Stadium",
    last_synced_at: null,
    data_status: "FRESH",
    events: [],
    ...over,
  }
}

describe("MatchHeader", () => {
  it("LIVE: score, minute and a spoken summary", async () => {
    await render(<MatchHeader match={match()} />)
    expect(screen.getByText("2 – 1")).toBeTruthy()
    expect(screen.getByText("LIVE")).toBeTruthy()
    expect(screen.getByText("67'")).toBeTruthy()
    expect(screen.getByLabelText("Arsenal 2, Chelsea 1. LIVE 67'")).toBeTruthy()
  })

  it("FULL TIME shows the final score and no minute", async () => {
    await render(<MatchHeader match={match({ status: "finished", minute: null })} />)
    expect(screen.getByText("FULL TIME")).toBeTruthy()
    expect(screen.getByText("2 – 1")).toBeTruthy()
    expect(screen.queryByText("67'")).toBeNull()
  })

  it("an upcoming match shows kickoff time instead of a score", async () => {
    await render(<MatchHeader match={match({ status: "scheduled", minute: null, home_score: 0, away_score: 0 })} />)
    expect(screen.getByText("18:30")).toBeTruthy()
    expect(screen.queryByText("0 – 0")).toBeNull()
    expect(screen.getByLabelText(/Arsenal versus Chelsea/)).toBeTruthy()
  })

  it("POSTPONED shows the status and no score", async () => {
    await render(<MatchHeader match={match({ status: "postponed", minute: null })} />)
    expect(screen.getByText("POSTPONED")).toBeTruthy()
    expect(screen.queryByText("2 – 1")).toBeNull()
  })

  it("HALF TIME is shown as such", async () => {
    await render(<MatchHeader match={match({ status: "halftime", minute: 45 })} />)
    expect(screen.getByText("HALF TIME")).toBeTruthy()
  })
})

describe("timeline", () => {
  const events: MatchEventOut[] = [
    { id: 3, event_type: "yellow_card", minute: 46, extra_minute: null, team: AWAY, player: { id: 9, name: "Caicedo", position: null, photo_url: null }, assist_player: null, description: null },
    { id: 2, event_type: "goal", minute: 45, extra_minute: 2, team: HOME, player: { id: 5, name: "Saka", position: null, photo_url: null }, assist_player: { id: 6, name: "Odegaard", position: null, photo_url: null }, description: null },
    { id: 1, event_type: "substitution", minute: 30, extra_minute: null, team: HOME, player: { id: 8, name: "Rodrygo", position: null, photo_url: null }, assist_player: { id: 7, name: "Vinícius Jr.", position: null, photo_url: null }, description: null },
  ]

  it("builds a chronological list with added time ordered correctly", async () => {
    expect(buildTimeline(match({ events })).map((i) => i.minuteLabel)).toEqual(["30'", "45+2'", "46'"])
  })

  it("rows expose a full sentence to screen readers", async () => {
    const [sub, goal] = buildTimeline(match({ events }))
    await render(
      <>
        <TimelineRow item={sub} />
        <TimelineRow item={goal} />
      </>,
    )
    expect(screen.getByLabelText("30' Substitution for Arsenal: Rodrygo on, Vinícius Jr. off")).toBeTruthy()
    expect(screen.getByLabelText("45+2' Goal by Saka for Arsenal")).toBeTruthy()
    expect(screen.getByText("Vinícius Jr. → Rodrygo")).toBeTruthy()
    expect(screen.getByText("Assist: Odegaard")).toBeTruthy()
  })
})

describe("StatRowView", () => {
  it("renders supplied values and a dash for a side that wasn't supplied", async () => {
    const [row] = statRows({
      home: { team_id: 1, possession: null, shots: null, shots_on_target: null, corners: 6, fouls: null, offsides: null, yellow_cards: null, red_cards: null, pass_accuracy: null, expected_goals: null },
      away: { team_id: 2, possession: null, shots: null, shots_on_target: null, corners: null, fouls: null, offsides: null, yellow_cards: null, red_cards: null, pass_accuracy: null, expected_goals: null },
    })
    await render(<StatRowView row={row} homeName="Arsenal" awayName="Chelsea" />)
    expect(screen.getByLabelText("Corners: Arsenal 6, Chelsea –")).toBeTruthy()
  })
})

describe("lineup rows", () => {
  const player = (id: number) => ({ id, name: "Saka", position: "Forward", photo_url: null })

  it("shows substitution minutes and links to the player page", async () => {
    await render(
      <LineupPlayerRow
        entry={{ player: player(5), position: "Forward", shirt_number: 7, is_starter: true, subbed_in_minute: null, subbed_out_minute: 61 }}
      />,
    )
    expect(screen.getByText("↓ 61'")).toBeTruthy()
    expect(screen.getByLabelText("Number 7, Saka, Forward, Substituted off 61 minutes")).toBeTruthy()
    expect(screen.getByRole("link").props.testHref).toContain("/player/[id]")
  })

  it("a placeholder player from a live event (id -1) is not linked", async () => {
    await render(
      <LineupPlayerRow
        entry={{ player: player(-1), position: null, shirt_number: null, is_starter: false, subbed_in_minute: 70, subbed_out_minute: null }}
      />,
    )
    expect(screen.queryByRole("link")).toBeNull()
    expect(screen.getByText("↑ 70'")).toBeTruthy()
  })
})

describe("standings", () => {
  const row = (over: Partial<StandingEntry> = {}): StandingEntry => ({
    position: 1,
    team: HOME,
    played: 8,
    won: 6,
    drawn: 1,
    lost: 1,
    goals_for: 19,
    goals_against: 8,
    points: 19,
    goal_difference: 11,
    season: "2026/27",
    group_name: "",
    description: "Champions League",
    form: "WWDLW",
    ...over,
  })

  it("a row announces position, record, goal difference and the provider's classification", async () => {
    await render(<StandingRowView row={row()} />)
    expect(
      screen.getByLabelText(
        "1. Arsenal, played 8, won 6, drawn 1, lost 1, goal difference +11, 19 points, Champions League",
      ),
    ).toBeTruthy()
    expect(screen.getByText("+11")).toBeTruthy()
  })

  it("negative goal difference isn't prefixed with a plus", async () => {
    await render(<StandingRowView row={row({ goals_for: 5, goals_against: 9, goal_difference: -4, description: null })} />)
    expect(screen.getByText("-4")).toBeTruthy()
  })

  it("the legend lists each distinct classification once, and nothing when there are none", async () => {
    const { rerender } = await render(
      <StandingsLegend standings={[row(), row({ team: AWAY, position: 2 }), row({ team: AWAY, description: "Relegation" })]} />,
    )
    expect(screen.getAllByText("Champions League")).toHaveLength(1)
    expect(screen.getByText("Relegation")).toBeTruthy()
    await rerender(<StandingsLegend standings={[row({ description: null })]} />)
    expect(screen.queryByText("Champions League")).toBeNull()
  })
})

describe("HeadToHeadSection", () => {
  const data = (meetings: HeadToHeadOut["meetings"]): HeadToHeadOut => ({
    home_team_id: 1,
    away_team_id: 2,
    limit: 5,
    period_start: "2016-10-01T00:00:00Z",
    before: "2026-10-01T00:00:00Z",
    meetings,
    home_team_wins: 1,
    draws: 1,
    away_team_wins: 0,
  })

  it("states the period and a spoken summary", async () => {
    const comp = { id: 1, name: "PL", country: null, logo_url: null, type: "league" }
    await render(
      <HeadToHeadSection
        match={match()}
        data={data([
          { match_id: 11, kickoff_time: "2026-02-01T15:00:00Z", competition: comp, home_team: HOME, away_team: AWAY, home_score: 2, away_score: 1 },
          { match_id: 12, kickoff_time: "2025-02-01T15:00:00Z", competition: comp, home_team: AWAY, away_team: HOME, home_score: 0, away_score: 0 },
        ])}
      />,
    )
    expect(screen.getByText("Last 2 since Oct 2016")).toBeTruthy()
    expect(screen.getByLabelText("Head to head: Arsenal 1 wins, 1 draws, Chelsea 0 wins")).toBeTruthy()
    expect(screen.getAllByRole("link")).toHaveLength(2)
  })

  it("an empty history says so", async () => {
    await render(<HeadToHeadSection match={match()} data={data([])} />)
    expect(screen.getByText("No previous meetings stored for these teams.")).toBeTruthy()
  })
})
