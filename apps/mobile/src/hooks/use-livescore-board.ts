import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { AppState, type AppStateStatus } from "react-native"
import { api } from "@/lib/api"
import { ConnectionStatus, RealtimeConnection } from "@/lib/realtime"
import type { MatchSummary, RealtimeMessage } from "@/types/api"

const WS_BASE_URL = process.env.EXPO_PUBLIC_WS_URL ?? "ws://localhost:8000"

function mergeById(lists: MatchSummary[][]): Map<number, MatchSummary> {
  const map = new Map<number, MatchSummary>()
  for (const list of lists) {
    for (const match of list) map.set(match.id, match)
  }
  return map
}

function applyRealtimeMessage(
  map: Map<number, MatchSummary>,
  message: RealtimeMessage,
): Map<number, MatchSummary> {
  const matchId = Number(message.match.id)
  const existing = map.get(matchId)
  if (!existing) return map

  const next = new Map(map)
  next.set(matchId, {
    ...existing,
    home_score: message.match.home_score,
    away_score: message.match.away_score,
    status: message.match.status,
    minute: message.match.minute,
    last_synced_at: new Date().toISOString(),
    data_status: "FRESH",
  })
  return next
}

export interface LivescoreBoardState {
  live: MatchSummary[]
  today: MatchSummary[]
  upcoming: MatchSummary[]
  finished: MatchSummary[]
  connectionStatus: ConnectionStatus
}

/**
 * Mirrors `apps/web/hooks/use-livescore-board.ts`'s data/merge logic, plus
 * app-lifecycle handling (spec §19): the WebSocket closes when the app is
 * backgrounded (no point maintaining a live connection nobody can see) and
 * reconnects -- after a REST refresh, so nothing missed while backgrounded
 * is lost -- when it returns to the foreground.
 */
export function useLivescoreBoard(
  initialLive: MatchSummary[],
  initialToday: MatchSummary[],
  initialUpcoming: MatchSummary[],
): LivescoreBoardState {
  const [matchMap, setMatchMap] = useState(() => mergeById([initialLive, initialToday, initialUpcoming]))
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting")
  const connectionRef = useRef<RealtimeConnection | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [live, today, upcoming] = await Promise.all([
        api.getLiveMatches(),
        api.getTodayMatches(),
        api.getUpcomingMatches(),
      ])
      setMatchMap(mergeById([live, today, upcoming]))
    } catch {
      // keep the last known state on a failed refresh
    }
  }, [])

  useEffect(() => {
    const connection = new RealtimeConnection({
      url: `${WS_BASE_URL}/ws/matches`,
      onStatusChange: setConnectionStatus,
      onMessage: (message) => setMatchMap((prev) => applyRealtimeMessage(prev, message)),
      onReconnect: refresh,
    })
    connectionRef.current = connection
    connection.connect()

    const subscription = AppState.addEventListener("change", (next: AppStateStatus) => {
      if (next === "background") {
        connection.close()
      } else if (next === "active") {
        void refresh()
        connection.connect()
      }
    })

    return () => {
      subscription.remove()
      connection.close()
      connectionRef.current = null
    }
  }, [refresh])

  return useMemo(() => {
    const all = Array.from(matchMap.values())
    const now = new Date()
    const todayKey = now.toISOString().slice(0, 10)
    const isToday = (m: MatchSummary) => m.kickoff_time.slice(0, 10) === todayKey

    return {
      live: all.filter((m) => m.status === "live" || m.status === "halftime"),
      today: all.filter(isToday),
      upcoming: all.filter((m) => m.status === "scheduled" && new Date(m.kickoff_time) > now),
      finished: all.filter((m) => isToday(m) && m.status === "finished"),
      connectionStatus,
    }
  }, [matchMap, connectionStatus])
}
