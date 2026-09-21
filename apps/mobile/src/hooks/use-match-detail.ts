import { useCallback, useEffect, useState } from "react"
import { AppState, type AppStateStatus } from "react-native"
import { api } from "@/lib/api"
import { ConnectionStatus, RealtimeConnection } from "@/lib/realtime"
import type { MatchDetail, RealtimeMessage } from "@/types/api"

const WS_BASE_URL = process.env.EXPO_PUBLIC_WS_URL ?? "ws://localhost:8000"

function applyRealtimeMessage(match: MatchDetail, message: RealtimeMessage): MatchDetail {
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

/** Mirrors `apps/web/hooks/use-match-detail.ts`, plus app-lifecycle
 * handling (spec §19) the same way `use-livescore-board.ts` does. */
export function useMatchDetail(initial: MatchDetail): MatchDetailState {
  const [match, setMatch] = useState(initial)
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting")

  const refresh = useCallback(async () => {
    try {
      setMatch(await api.getMatch(initial.id))
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
    }
  }, [initial.id, refresh])

  return { match, connectionStatus }
}
