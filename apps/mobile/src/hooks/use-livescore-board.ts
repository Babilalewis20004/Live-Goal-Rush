import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { AppState, type AppStateStatus } from "react-native"
import { NUDGE_TYPES } from "@/hooks/use-match-detail"
import { api } from "@/lib/api"
import { saveCopy } from "@/lib/offline-cache"
import { ConnectionStatus, RealtimeConnection } from "@/lib/realtime"
import type { MatchSummary, RealtimeMessage } from "@/types/api"

const WS_BASE_URL = process.env.EXPO_PUBLIC_WS_URL ?? "ws://localhost:8000"
export const BOARD_CACHE_KEY = "home-board"

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
  /** Epoch ms of the last REST refresh or live message that confirmed these scores (Phase 7 degraded mode). */
  lastUpdatedAt: number
  /** True while the last REST refresh failed, or the board started from a saved copy that no refresh has replaced. */
  lastRefreshFailed: boolean
  /** True until the first successful refresh when the board was seeded from an on-device copy. */
  showingSavedCopy: boolean
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
  /** Epoch ms the seed data was saved at, when it came from the on-device copy rather than the network. */
  savedAt: number | null = null,
): LivescoreBoardState {
  const [matchMap, setMatchMap] = useState(() => mergeById([initialLive, initialToday, initialUpcoming]))
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting")
  const [lastUpdatedAt, setLastUpdatedAt] = useState(() => savedAt ?? Date.now())
  const [lastRefreshFailed, setLastRefreshFailed] = useState(savedAt !== null)
  const [showingSavedCopy, setShowingSavedCopy] = useState(savedAt !== null)
  const connectionRef = useRef<RealtimeConnection | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [live, today, upcoming] = await Promise.all([
        api.getLiveMatches(),
        api.getTodayMatches(),
        api.getUpcomingMatches(),
      ])
      setMatchMap(mergeById([live, today, upcoming]))
      setLastUpdatedAt(Date.now())
      setLastRefreshFailed(false)
      setShowingSavedCopy(false)
      void saveCopy(BOARD_CACHE_KEY, { live, today, upcoming })
    } catch {
      // keep the last known state on a failed refresh -- but say so: it is no longer confirmed current
      setLastRefreshFailed(true)
    }
  }, [])

  useEffect(() => {
    const connection = new RealtimeConnection({
      url: `${WS_BASE_URL}/ws/matches`,
      onStatusChange: setConnectionStatus,
      onMessage: (message) => {
        if (NUDGE_TYPES.has(message.type)) return // community nudges carry no score
        setMatchMap((prev) => applyRealtimeMessage(prev, message))
        setLastUpdatedAt(Date.now())
      },
      onReconnect: refresh,
    })
    connectionRef.current = connection
    connection.connect()
    // Started from a saved copy: replace it with the real thing the moment the network allows. Deferred so the
    // refresh's state updates never run synchronously inside the effect (react-hooks/set-state-in-effect).
    const catchUp = savedAt !== null ? setTimeout(() => void refresh(), 0) : null

    const subscription = AppState.addEventListener("change", (next: AppStateStatus) => {
      if (next === "background") {
        connection.close()
      } else if (next === "active") {
        void refresh()
        connection.connect()
      }
    })

    return () => {
      if (catchUp) clearTimeout(catchUp)
      subscription.remove()
      connection.close()
      connectionRef.current = null
    }
  }, [refresh, savedAt])

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
      lastUpdatedAt,
      lastRefreshFailed,
      showingSavedCopy,
    }
  }, [matchMap, connectionStatus, lastUpdatedAt, lastRefreshFailed, showingSavedCopy])
}
