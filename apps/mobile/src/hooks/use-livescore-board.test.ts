import { act, renderHook, waitFor } from "@testing-library/react-native"

import { api } from "@/lib/api"
import type { MatchSummary, RealtimeMessage } from "@/types/api"
import { useLivescoreBoard } from "./use-livescore-board"

interface FakeConnection {
  options: { onMessage: (m: RealtimeMessage) => void; onReconnect?: () => void | Promise<void>; onStatusChange?: (s: string) => void }
  connect: jest.Mock
  close: jest.Mock
}
const connections: FakeConnection[] = []

jest.mock("@/lib/realtime", () => ({
  RealtimeConnection: class {
    options: FakeConnection["options"]
    connect = jest.fn()
    close = jest.fn()
    constructor(options: FakeConnection["options"]) {
      this.options = options
      connections.push(this as unknown as FakeConnection)
    }
  },
}))

jest.mock("@/lib/api", () => ({
  api: { getLiveMatches: jest.fn(), getTodayMatches: jest.fn(), getUpcomingMatches: jest.fn() },
}))

const mockApi = api as unknown as Record<"getLiveMatches" | "getTodayMatches" | "getUpcomingMatches", jest.Mock>

const team = (id: number, name: string) => ({ id, name, short_name: null, country: null, logo_url: null })
const match = (id: number, over: Partial<MatchSummary> = {}): MatchSummary => ({
  id,
  competition: { id: 1, name: "PL", country: null, logo_url: null, type: "league" },
  home_team: team(1, "Arsenal"),
  away_team: team(2, "Chelsea"),
  kickoff_time: new Date().toISOString(),
  status: "live",
  home_score: 0,
  away_score: 0,
  half_time_home_score: null,
  half_time_away_score: null,
  minute: 10,
  venue: null,
  last_synced_at: null,
  data_status: "FRESH",
  ...over,
})

beforeEach(() => {
  connections.length = 0
  jest.clearAllMocks()
})

describe("useLivescoreBoard freshness", () => {
  it("starts fresh and moves forward on every live message", async () => {
    const live = [match(7)]
    const { result } = await renderHook(() => useLivescoreBoard(live, live, []))
    const before = result.current.lastUpdatedAt
    expect(result.current.lastRefreshFailed).toBe(false)
    expect(result.current.showingSavedCopy).toBe(false)

    await new Promise((r) => setTimeout(r, 5))
    await act(async () => {
      connections[0].options.onMessage({ type: "GOAL", match: { id: "7", home_score: 1, away_score: 0, status: "live", minute: 12 } } as RealtimeMessage)
    })
    expect(result.current.lastUpdatedAt).toBeGreaterThan(before)
    expect(result.current.live[0].home_score).toBe(1)
  })

  it("keeps showing the last scores but flags them when a refresh fails", async () => {
    mockApi.getLiveMatches.mockRejectedValue(new Error("offline"))
    mockApi.getTodayMatches.mockRejectedValue(new Error("offline"))
    mockApi.getUpcomingMatches.mockRejectedValue(new Error("offline"))
    const live = [match(7, { home_score: 2 })]
    const { result } = await renderHook(() => useLivescoreBoard(live, live, []))

    await act(async () => {
      await connections[0].options.onReconnect?.()
    })
    expect(result.current.live[0].home_score).toBe(2) // not blanked
    expect(result.current.lastRefreshFailed).toBe(true)
  })

  it("replaces a saved copy as soon as a refresh succeeds", async () => {
    const fresh = [match(7, { home_score: 3 })]
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    // the network answers only when the test lets it, so the "still a saved copy" moment can be observed
    mockApi.getLiveMatches.mockImplementation(async () => (await gate, fresh))
    mockApi.getTodayMatches.mockImplementation(async () => (await gate, fresh))
    mockApi.getUpcomingMatches.mockImplementation(async () => (await gate, []))
    const stale = [match(7, { home_score: 1 })]
    const savedAt = Date.now() - 3 * 3_600_000

    const { result } = await renderHook(() => useLivescoreBoard(stale, stale, [], savedAt))
    expect(result.current.showingSavedCopy).toBe(true)
    expect(result.current.lastRefreshFailed).toBe(true)
    expect(result.current.lastUpdatedAt).toBe(savedAt)
    expect(result.current.live[0].home_score).toBe(1) // the saved score, until the network answers

    await act(async () => {
      release()
    })
    await waitFor(() => expect(result.current.showingSavedCopy).toBe(false))
    expect(result.current.lastRefreshFailed).toBe(false)
    expect(result.current.live[0].home_score).toBe(3)
    expect(result.current.lastUpdatedAt).toBeGreaterThan(savedAt)
  })

  it("stays flagged as a saved copy while the network is still down", async () => {
    mockApi.getLiveMatches.mockRejectedValue(new Error("offline"))
    mockApi.getTodayMatches.mockRejectedValue(new Error("offline"))
    mockApi.getUpcomingMatches.mockRejectedValue(new Error("offline"))
    const stale = [match(7)]
    const { result } = await renderHook(() => useLivescoreBoard(stale, stale, [], Date.now() - 60_000))
    await waitFor(() => expect(mockApi.getLiveMatches).toHaveBeenCalled())
    expect(result.current.showingSavedCopy).toBe(true)
  })
})
