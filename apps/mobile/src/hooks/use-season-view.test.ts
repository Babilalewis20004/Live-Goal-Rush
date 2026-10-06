import { act, renderHook } from "@testing-library/react-native"

import { api } from "@/lib/api"
import { SEASON_POLL } from "@/lib/seasons"
import type { CompetitionSeasonsOut, StandingEntry, TopScorersOut } from "@/types/api"
import { useSeasonView } from "./use-season-view"

jest.mock("@/lib/api", () => ({
  api: { getStandings: jest.fn(), getTopScorers: jest.fn() },
}))
const mockApi = api as unknown as Record<"getStandings" | "getTopScorers", jest.Mock>

const row = (season: string): StandingEntry => ({
  position: 1,
  team: { id: 1, name: "Arsenal", short_name: "ARS", country: null, logo_url: null },
  played: 38,
  won: 28,
  drawn: 5,
  lost: 5,
  goals_for: 80,
  goals_against: 30,
  points: 89,
  goal_difference: 50,
  season,
  group_name: "",
  description: null,
  form: null,
})
const scorers = (season: string): TopScorersOut => ({ competition_id: 2, season, scorers: [] })

const INFO: CompetitionSeasonsOut = { current: "2026/27", seasons: ["2026/27", "2025/26"], historical_supported: true }
const INITIAL = { standings: [row("2026/27")], topScorers: scorers("2026/27") }

beforeEach(() => {
  jest.useFakeTimers()
  mockApi.getStandings.mockReset()
  mockApi.getTopScorers.mockReset()
  mockApi.getTopScorers.mockResolvedValue(scorers("x"))
})
afterEach(() => jest.useRealTimers())

async function flush() {
  await act(async () => {
    jest.advanceTimersByTime(0)
  })
}

describe("useSeasonView", () => {
  it("starts on the server-rendered current season and makes no request", async () => {
    const { result } = await renderHook(() => useSeasonView(2, INITIAL, INFO))
    await flush()
    expect(result.current.season).toBeNull()
    expect(result.current.standings).toBe(INITIAL.standings)
    expect(mockApi.getStandings).not.toHaveBeenCalled()
  })

  it("selecting a stored season fetches it straight away", async () => {
    mockApi.getStandings.mockResolvedValue([row("2025/26")])
    const { result } = await renderHook(() => useSeasonView(2, INITIAL, INFO))
    await act(async () => result.current.select("2025/26"))
    expect(result.current.loading).toBe(true) // never shows the old table under the new name
    await flush()
    expect(mockApi.getStandings).toHaveBeenCalledWith(2, "2025/26")
    expect(result.current.standings?.[0].season).toBe("2025/26")
    expect(result.current.loading).toBe(false)
  })

  it("a past season still being backfilled keeps loading and re-checks until it appears", async () => {
    mockApi.getStandings.mockResolvedValueOnce([]).mockResolvedValueOnce([]).mockResolvedValue([row("2024/25")])
    const { result } = await renderHook(() => useSeasonView(2, INITIAL, INFO))
    await act(async () => result.current.select("2024/25"))
    await flush()
    expect(result.current.loading).toBe(true)
    expect(result.current.gaveUp).toBe(false)

    await act(async () => {
      jest.advanceTimersByTime(SEASON_POLL.intervalMs)
    })
    expect(result.current.loading).toBe(true) // second check: still empty
    await act(async () => {
      jest.advanceTimersByTime(SEASON_POLL.intervalMs)
    })
    expect(mockApi.getStandings).toHaveBeenCalledTimes(3)
    expect(result.current.loading).toBe(false)
    expect(result.current.standings?.[0].season).toBe("2024/25")
  })

  it("gives up after the poll budget when the provider has no such season", async () => {
    mockApi.getStandings.mockResolvedValue([])
    const { result } = await renderHook(() => useSeasonView(2, INITIAL, INFO))
    await act(async () => result.current.select("2019/20"))
    await flush()
    for (let i = 0; i < SEASON_POLL.attempts; i++) {
      await act(async () => {
        jest.advanceTimersByTime(SEASON_POLL.intervalMs)
      })
    }
    expect(mockApi.getStandings).toHaveBeenCalledTimes(SEASON_POLL.attempts)
    expect(result.current.loading).toBe(false)
    expect(result.current.gaveUp).toBe(true)
  })

  it("does not poll when the provider has no history: one answer is final", async () => {
    mockApi.getStandings.mockResolvedValue([])
    const { result } = await renderHook(() =>
      useSeasonView(2, INITIAL, { ...INFO, historical_supported: false }),
    )
    await act(async () => result.current.select("2025/26"))
    await flush()
    await act(async () => {
      jest.advanceTimersByTime(SEASON_POLL.intervalMs * 3)
    })
    expect(mockApi.getStandings).toHaveBeenCalledTimes(1)
    expect(result.current.gaveUp).toBe(true)
  })

  it("going back to the current season restores the server data and cancels any polling", async () => {
    mockApi.getStandings.mockResolvedValue([])
    const { result } = await renderHook(() => useSeasonView(2, INITIAL, INFO))
    await act(async () => result.current.select("2024/25"))
    await flush()
    await act(async () => result.current.select(null))
    expect(result.current.standings).toBe(INITIAL.standings)
    expect(result.current.loading).toBe(false)
    const calls = mockApi.getStandings.mock.calls.length
    await act(async () => {
      jest.advanceTimersByTime(SEASON_POLL.intervalMs * 4)
    })
    expect(mockApi.getStandings.mock.calls.length).toBe(calls)
  })

  it("a late answer for a season the user has since left is discarded", async () => {
    let release!: (rows: StandingEntry[]) => void
    mockApi.getStandings
      .mockReturnValueOnce(new Promise<StandingEntry[]>((r) => (release = r)))
      .mockResolvedValue([row("2025/26")])
    const { result } = await renderHook(() => useSeasonView(2, INITIAL, INFO))
    await act(async () => result.current.select("2024/25"))
    await flush()
    await act(async () => result.current.select("2025/26"))
    await flush()
    await act(async () => release([row("2024/25")])) // the stale response arrives last
    expect(result.current.season).toBe("2025/26")
    expect(result.current.standings?.[0].season).toBe("2025/26")
  })
})
