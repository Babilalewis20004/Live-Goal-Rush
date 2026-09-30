"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"
import { refreshPlanFor } from "@/lib/match-centre"
import { ConnectionStatus, RealtimeConnection } from "@/lib/realtime"
import type {
  Capabilities,
  MatchDetail,
  MatchLineupsOut,
  MatchStatisticsOut,
  RealtimeMessage,
  StandingEntry,
} from "@/types/api"

const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000"

export function applyRealtimeMessage(match: MatchDetail, message: RealtimeMessage): MatchDetail {
  if (Number(message.match.id) !== match.id) return match

  const events = [...match.events]
  const incoming = message.match.event
  if (incoming && !events.some((e) => e.id === incoming.id)) {
    const team =
      match.home_team.id === incoming.team_id
        ? match.home_team
        : match.away_team.id === incoming.team_id
          ? match.away_team
          : null
    events.push({
      id: incoming.id,
      event_type: incoming.event_type,
      minute: incoming.minute,
      extra_minute: incoming.extra_minute ?? null,
      team,
      // The realtime payload carries player *names*, not full PlayerOut
      // records (id/position/photo) -- enough for the timeline, which only
      // reads `.name`. The next REST refresh (a reconnect, or navigating
      // back to the page) replaces these with the real records.
      player: incoming.player ? { id: -1, name: incoming.player, position: null, photo_url: null } : null,
      assist_player: incoming.assist ? { id: -1, name: incoming.assist, position: null, photo_url: null } : null,
      description: incoming.description,
      event_detail: incoming.event_detail ?? null,
    })
    events.sort((a, b) => a.minute - b.minute || (a.extra_minute ?? 0) - (b.extra_minute ?? 0) || a.id - b.id)
  }

  return {
    ...match,
    home_score: message.match.home_score,
    away_score: message.match.away_score,
    status: message.match.status,
    minute: message.match.minute,
    last_synced_at: new Date().toISOString(),
    data_status: "FRESH",
    events,
  }
}

/** The non-score match-centre data that arrives over REST and is kept fresh
 * by the same WebSocket (see `refreshPlanFor`). `null` = not loaded /
 * not supplied. */
export interface MatchCentreExtras {
  lineups: MatchLineupsOut | null
  statistics: MatchStatisticsOut | null
  standings: StandingEntry[] | null
}

export interface MatchDetailState extends MatchCentreExtras {
  match: MatchDetail
  connectionStatus: ConnectionStatus
  /** ISO time of the last successful REST refresh or WebSocket message. */
  lastUpdatedAt: string | null
}

/** Real-time data hook for the match centre: seeds from the server-fetched
 * initial data, then keeps one socket open on `/ws/matches/{id}` (no second
 * pipeline) -- score/status/events are applied directly, statistics come in
 * the message, and lineups/standings are re-fetched when a message says they
 * changed. A reconnect re-fetches everything over REST before resubscribing. */
export function useMatchDetail(
  initial: MatchDetail,
  initialExtras: Partial<MatchCentreExtras> = {},
  capabilities: Capabilities | null = null,
): MatchDetailState {
  const [match, setMatch] = useState(initial)
  const [lineups, setLineups] = useState<MatchLineupsOut | null>(initialExtras.lineups ?? null)
  const [statistics, setStatistics] = useState<MatchStatisticsOut | null>(initialExtras.statistics ?? null)
  const [standings, setStandings] = useState<StandingEntry[] | null>(initialExtras.standings ?? null)
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting")
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(initial.last_synced_at)

  const competitionId = initial.competition.id
  const wantsLineups = capabilities ? capabilities.lineups : true
  const wantsStatistics = capabilities ? capabilities.match_statistics : true
  const inFlight = useRef<Set<string>>(new Set())

  /** Runs `task` unless an identical one is already in flight (a burst of
   * messages must not fan out into duplicate requests). */
  const once = useCallback(async (key: string, task: () => Promise<void>) => {
    if (inFlight.current.has(key)) return
    inFlight.current.add(key)
    try {
      await task()
    } catch {
      // keep the last known data on a failed refresh
    } finally {
      inFlight.current.delete(key)
    }
  }, [])

  const loadLineups = useCallback(
    () => once("lineups", async () => setLineups(await api.getMatchLineups(initial.id))),
    [initial.id, once],
  )
  const loadStatistics = useCallback(
    () => once("statistics", async () => setStatistics(await api.getMatchStatistics(initial.id))),
    [initial.id, once],
  )
  const loadStandings = useCallback(
    () => once("standings", async () => setStandings(await api.getStandings(competitionId))),
    [competitionId, once],
  )

  const refresh = useCallback(async () => {
    await once("match", async () => {
      setMatch(await api.getMatch(initial.id))
      setLastUpdatedAt(new Date().toISOString())
    })
    const jobs: Promise<void>[] = []
    if (wantsLineups) jobs.push(loadLineups())
    if (wantsStatistics) jobs.push(loadStatistics())
    jobs.push(loadStandings())
    await Promise.all(jobs)
  }, [initial.id, once, wantsLineups, wantsStatistics, loadLineups, loadStatistics, loadStandings])

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = []
    const connection = new RealtimeConnection({
      url: `${WS_BASE_URL}/ws/matches/${initial.id}`,
      onStatusChange: setConnectionStatus,
      onMessage: (message) => {
        if (Number(message.match.id) !== initial.id) return
        setMatch((prev) => applyRealtimeMessage(prev, message))
        setLastUpdatedAt(new Date().toISOString())
        if (message.match.statistics) setStatistics(message.match.statistics)

        const plan = refreshPlanFor(message)
        if (plan.lineups && wantsLineups) void loadLineups()
        if (plan.statistics && wantsStatistics) void loadStatistics()
        if (plan.standings) {
          // The official table is re-synced by a queued worker job *after*
          // full time, so an immediate fetch would usually still see the old
          // table: check again shortly, and once more for a slow sync.
          timers.push(setTimeout(() => void loadStandings(), 6_000), setTimeout(() => void loadStandings(), 25_000))
        }
      },
      onReconnect: refresh,
    })
    connection.connect()
    return () => {
      timers.forEach(clearTimeout)
      connection.close()
    }
  }, [initial.id, refresh, loadLineups, loadStatistics, loadStandings, wantsLineups, wantsStatistics])

  return { match, connectionStatus, lastUpdatedAt, lineups, statistics, standings }
}
