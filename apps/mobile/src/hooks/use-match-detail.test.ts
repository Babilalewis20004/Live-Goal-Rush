import { act, renderHook, waitFor } from "@testing-library/react-native"

import { api } from "@/lib/api"
import type { MatchDetail, RealtimeMessage } from "@/types/api"
import { applyRealtimeMessage, useMatchDetail } from "./use-match-detail"

// -- test doubles ---------------------------------------------------------------------------
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
  api: {
    getMatch: jest.fn(),
    getMatchLineups: jest.fn(),
    getMatchStatistics: jest.fn(),
    getStandings: jest.fn(),
  },
}))

const mockApi = api as unknown as Record<"getMatch" | "getMatchLineups" | "getMatchStatistics" | "getStandings", jest.Mock>

const TEAM_A = { id: 1, name: "Arsenal", short_name: "ARS", country: null, logo_url: null }
const TEAM_B = { id: 2, name: "Chelsea", short_name: "CHE", country: null, logo_url: null }

function detail(over: Partial<MatchDetail> = {}): MatchDetail {
  return {
    id: 7,
    competition: { id: 3, name: "PL", country: null, logo_url: null, type: "league" },
    home_team: TEAM_A,
    away_team: TEAM_B,
    kickoff_time: "2026-10-01T18:00:00Z",
    status: "live",
    home_score: 0,
    away_score: 0,
    half_time_home_score: null,
    half_time_away_score: null,
    minute: 10,
    venue: null,
    last_synced_at: "2026-10-01T18:10:00Z",
    data_status: "FRESH",
    events: [],
    ...over,
  }
}

const message = (type: RealtimeMessage["type"], match: Partial<RealtimeMessage["match"]> = {}): RealtimeMessage => ({
  type,
  match: { id: "7", home_score: 0, away_score: 0, status: "live", minute: 11, ...match },
})

const current = () => connections[connections.length - 1]

beforeEach(() => {
  connections.length = 0
  for (const fn of Object.values(mockApi)) fn.mockReset()
  mockApi.getMatchLineups.mockResolvedValue({ home: null, away: null })
  mockApi.getMatchStatistics.mockResolvedValue({ home: null, away: null })
  mockApi.getStandings.mockResolvedValue([])
})

describe("applyRealtimeMessage", () => {
  it("ignores a message for another match", () => {
    const m = detail()
    expect(applyRealtimeMessage(m, message("GOAL", { id: "99", home_score: 5 }))).toBe(m)
  })
})

describe("useMatchDetail", () => {
  it("opens one socket for the match and closes it on unmount", async () => {
    const { unmount } = await renderHook(() => useMatchDetail(detail()))
    expect(connections).toHaveLength(1)
    expect(current().connect).toHaveBeenCalled()
    await unmount()
    expect(current().close).toHaveBeenCalled()
  })

  it("applies a goal to the score and the timeline", async () => {
    const { result } = await renderHook(() => useMatchDetail(detail()))
    await act(async () => {
      current().options.onMessage(
        message("GOAL", {
          home_score: 1,
          event: { id: 5, event_type: "goal", minute: 11, team_id: 1, player: "Saka", description: null },
        }),
      )
    })
    expect(result.current.match.home_score).toBe(1)
    expect(result.current.match.events.map((e) => e.player?.name)).toEqual(["Saka"])
    expect(result.current.lastUpdatedAt).not.toBeNull()
  })

  it("ignores messages about other matches entirely", async () => {
    const { result } = await renderHook(() => useMatchDetail(detail()))
    await act(async () => {
      current().options.onMessage(message("GOAL", { id: "99", home_score: 3 }))
    })
    expect(result.current.match.home_score).toBe(0)
    expect(mockApi.getMatchLineups).not.toHaveBeenCalled()
  })

  it("STATISTICS_UPDATED carries the numbers: applied directly, no extra request", async () => {
    const { result } = await renderHook(() => useMatchDetail(detail()))
    const stats = { home: { team_id: 1, shots: 4 }, away: null } as never
    await act(async () => {
      current().options.onMessage(message("STATISTICS_UPDATED", { statistics: stats }))
    })
    expect(result.current.statistics).toBe(stats)
    expect(mockApi.getMatchStatistics).not.toHaveBeenCalled()
  })

  it("LINEUP_UPDATED re-fetches lineups, and a burst of messages makes one request", async () => {
    let release!: (v: unknown) => void
    mockApi.getMatchLineups.mockReturnValue(new Promise((r) => (release = r)))
    const { result } = await renderHook(() => useMatchDetail(detail()))
    await act(async () => {
      current().options.onMessage(message("LINEUP_UPDATED"))
      current().options.onMessage(message("LINEUP_UPDATED"))
      current().options.onMessage(message("SUBSTITUTION"))
    })
    expect(mockApi.getMatchLineups).toHaveBeenCalledTimes(1) // coalesced while in flight
    const lineups = { home: null, away: null }
    await act(async () => release(lineups))
    await waitFor(() => expect(result.current.lineups).toEqual(lineups))
  })

  it("does not request lineups the provider never supplies", async () => {
    const caps = { lineups: false, match_statistics: true } as never
    await renderHook(() => useMatchDetail(detail(), {}, caps))
    await act(async () => {
      current().options.onMessage(message("LINEUP_UPDATED"))
    })
    expect(mockApi.getMatchLineups).not.toHaveBeenCalled()
  })

  describe("full time", () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    it("refreshes lineups at once and re-checks the table after the worker has had time to sync it", async () => {
      await renderHook(() => useMatchDetail(detail()))
      await act(async () => {
        current().options.onMessage(message("MATCH_FINISHED", { status: "finished", minute: null }))
      })
      expect(mockApi.getMatchLineups).toHaveBeenCalledTimes(1)
      expect(mockApi.getStandings).not.toHaveBeenCalled() // the sync runs *after* full time

      await act(async () => {
        jest.advanceTimersByTime(6_000)
      })
      expect(mockApi.getStandings).toHaveBeenCalledTimes(1)
      await act(async () => {
        jest.advanceTimersByTime(20_000)
      })
      expect(mockApi.getStandings).toHaveBeenCalledTimes(2) // the slow-sync re-check at 25 s
      expect(mockApi.getStandings).toHaveBeenCalledWith(3) // the match's competition
    })

    it("cancels the pending table re-checks when the screen goes away", async () => {
      const { unmount } = await renderHook(() => useMatchDetail(detail()))
      await act(async () => {
        current().options.onMessage(message("MATCH_FINISHED", { status: "finished", minute: null }))
      })
      await unmount()
      await act(async () => {
        jest.advanceTimersByTime(30_000)
      })
      expect(mockApi.getStandings).not.toHaveBeenCalled()
    })
  })

  it("on reconnect, re-fetches everything over REST before the socket reopens", async () => {
    mockApi.getMatch.mockResolvedValue(detail({ home_score: 2, minute: 55 }))
    const { result } = await renderHook(() => useMatchDetail(detail()))
    await act(async () => {
      await current().options.onReconnect?.()
    })
    expect(mockApi.getMatch).toHaveBeenCalledWith(7)
    expect(mockApi.getMatchLineups).toHaveBeenCalled()
    expect(mockApi.getMatchStatistics).toHaveBeenCalled()
    expect(mockApi.getStandings).toHaveBeenCalled()
    expect(result.current.match.home_score).toBe(2)
  })

  it("keeps the last known state when a refresh fails (the offline case)", async () => {
    mockApi.getMatch.mockRejectedValue(new Error("offline"))
    const { result } = await renderHook(() => useMatchDetail(detail({ home_score: 1 })))
    await act(async () => {
      await current().options.onReconnect?.()
    })
    expect(result.current.match.home_score).toBe(1)
  })

  it("reflects connection status changes", async () => {
    const { result } = await renderHook(() => useMatchDetail(detail()))
    expect(result.current.connectionStatus).toBe("connecting")
    await act(async () => {
      current().options.onStatusChange?.("reconnecting")
    })
    expect(result.current.connectionStatus).toBe("reconnecting")
  })
})
