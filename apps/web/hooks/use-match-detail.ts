"use client"

import { useCallback, useEffect, useState } from "react"
import { api } from "@/lib/api"
import { ConnectionStatus, RealtimeConnection } from "@/lib/realtime"
import type { MatchDetail, RealtimeMessage } from "@/types/api"

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
      extra_minute: null,
      team,
      // The realtime payload carries a player name, not a full PlayerOut
      // (id/position/photo) -- good enough for the event timeline's
      // rendering, which only reads `.name`. The next REST refresh (a
      // reconnect, or navigating back to the page) replaces this with the
      // real record.
      player: incoming.player ? { id: -1, name: incoming.player, position: null, photo_url: null } : null,
      assist_player: null,
      description: incoming.description,
    })
    events.sort((a, b) => a.minute - b.minute)
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

export interface MatchDetailState {
  match: MatchDetail
  connectionStatus: ConnectionStatus
}

/** Real-time data hook for the match detail page (spec §17): seeds from
 * the server-fetched initial detail, then subscribes to
 * `/ws/matches/{id}` so only updates for this one match are received. */
export function useMatchDetail(initial: MatchDetail): MatchDetailState {
  const [match, setMatch] = useState(initial)
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting")

  const refresh = useCallback(async () => {
    try {
      const fresh = await api.getMatch(initial.id)
      setMatch(fresh)
    } catch {
      // keep the last known state on a failed refresh
    }
  }, [initial.id])

  useEffect(() => {
    const connection = new RealtimeConnection({
      url: `${WS_BASE_URL}/ws/matches/${initial.id}`,
      onStatusChange: setConnectionStatus,
      onMessage: (message) => setMatch((prev) => applyRealtimeMessage(prev, message)),
      onReconnect: refresh,
    })
    connection.connect()
    return () => connection.close()
  }, [initial.id, refresh])

  return { match, connectionStatus }
}
