"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { api } from "@/lib/api"
import { ConnectionStatus, RealtimeConnection } from "@/lib/realtime"
import type { MatchSummary, RealtimeMessage } from "@/types/api"

const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000"

export function mergeById(lists: MatchSummary[][]): Map<number, MatchSummary> {
  const map = new Map<number, MatchSummary>()
  for (const list of lists) {
    for (const match of list) map.set(match.id, match)
  }
  return map
}

export function applyRealtimeMessage(
  map: Map<number, MatchSummary>,
  message: RealtimeMessage,
): Map<number, MatchSummary> {
  const matchId = Number(message.match.id)
  const existing = map.get(matchId)
  // An update for a match this client hasn't loaded yet (e.g. a brand new
  // fixture) isn't fabricated from the partial WebSocket payload -- it
  // shows up on the next REST refresh instead, which carries full data
  // (competition/team objects the realtime payload doesn't include).
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

/** Derives the four board views from one id-keyed match map, the same way
 * the backend derives them (kickoff date + status) rather than trusting
 * three separately-drifting arrays. Exported standalone for unit testing. */
export function deriveBoardState(
  matchMap: Map<number, MatchSummary>,
  connectionStatus: ConnectionStatus,
  now: Date = new Date(),
): LivescoreBoardState {
  const all = Array.from(matchMap.values())
  const todayKey = now.toISOString().slice(0, 10)
  const isToday = (m: MatchSummary) => m.kickoff_time.slice(0, 10) === todayKey

  return {
    live: all.filter((m) => m.status === "live" || m.status === "halftime"),
    today: all.filter(isToday),
    upcoming: all.filter((m) => m.status === "scheduled" && new Date(m.kickoff_time) > now),
    finished: all.filter((m) => isToday(m) && m.status === "finished"),
    connectionStatus,
  }
}

/**
 * One reusable real-time data hook for the home livescore board (spec
 * §20 -- avoids every page reimplementing its own WebSocket wiring).
 * Seeds from the server-fetched initial lists, then keeps a single
 * id-keyed match map up to date from `/ws/matches`, re-deriving the
 * live/today/upcoming/finished views from it exactly the way the backend
 * derives them (kickoff date + status) rather than trusting three
 * separately-drifting arrays.
 */
export function useLivescoreBoard(
  initialLive: MatchSummary[],
  initialToday: MatchSummary[],
  initialUpcoming: MatchSummary[],
): LivescoreBoardState {
  const [matchMap, setMatchMap] = useState(() => mergeById([initialLive, initialToday, initialUpcoming]))
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting")

  const refresh = useCallback(async () => {
    try {
      const [live, today, upcoming] = await Promise.all([
        api.getLiveMatches(),
        api.getTodayMatches(),
        api.getUpcomingMatches(),
      ])
      setMatchMap(mergeById([live, today, upcoming]))
    } catch {
      // Keep the last known state on a failed refresh -- connectionStatus
      // already reflects the WebSocket, which is the more relevant signal.
    }
  }, [])

  useEffect(() => {
    const connection = new RealtimeConnection({
      url: `${WS_BASE_URL}/ws/matches`,
      onStatusChange: setConnectionStatus,
      onMessage: (message) => setMatchMap((prev) => applyRealtimeMessage(prev, message)),
      onReconnect: refresh,
    })
    connection.connect()
    return () => connection.close()
  }, [refresh])

  return useMemo(() => deriveBoardState(matchMap, connectionStatus), [matchMap, connectionStatus])
}
