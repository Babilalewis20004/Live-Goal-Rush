import { Ionicons } from "@expo/vector-icons"
import { useLocalSearchParams } from "expo-router"
import { useCallback, useEffect, useState } from "react"
import { ScrollView, StyleSheet, Text, View } from "react-native"
import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { LoadingState } from "@/components/loading-state"
import { TeamBadge } from "@/components/team-badge"
import { ConnectionBadge } from "@/components/connection-badge"
import { useMatchDetail } from "@/hooks/use-match-detail"
import { api, ApiError } from "@/lib/api"
import { formatKickoff, formatKickoffDate } from "@/lib/format"
import { theme } from "@/theme"
import type { MatchDetail } from "@/types/api"

function statusLabel(status: string, minute: number | null): string {
  if (status === "live") return `${minute}'`
  if (status === "halftime") return "Half Time"
  if (status === "finished") return "Full Time"
  if (status === "postponed" || status === "cancelled") return status.toUpperCase()
  return "Scheduled"
}

export default function MatchScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const [initialMatch, setInitialMatch] = useState<MatchDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setInitialMatch(await api.getMatch(Number(id)))
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "Match not found." : "Unable to load this match.")
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const handle = setTimeout(load, 0)
    return () => clearTimeout(handle)
  }, [load])

  if (loading) {
    return (
      <View style={styles.screen}>
        <LoadingState label="Loading match…" />
      </View>
    )
  }

  if (error || !initialMatch) {
    return (
      <View style={styles.screen}>
        <ErrorState message={error ?? "Unable to load this match."} onRetry={load} />
      </View>
    )
  }

  return <LiveMatchScreen initialMatch={initialMatch} />
}

function LiveMatchScreen({ initialMatch }: { initialMatch: MatchDetail }) {
  const { match, connectionStatus } = useMatchDetail(initialMatch)
  const isLive = match.status === "live" || match.status === "halftime"

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.headerRow}>
        <ConnectionBadge status={connectionStatus} />
      </View>

      <View style={styles.card}>
        <Text style={styles.competition}>{match.competition.name}</Text>
        <View style={styles.scoreRow}>
          <View style={styles.teamCol}>
            <TeamBadge name={match.home_team.name} shortName={match.home_team.short_name} logoUrl={match.home_team.logo_url} size={48} />
            <Text style={styles.teamName} numberOfLines={1}>{match.home_team.name}</Text>
          </View>
          <View style={styles.scoreCol}>
            <Text style={styles.score}>{match.home_score} - {match.away_score}</Text>
            <View style={[styles.statusPill, isLive && styles.statusPillLive]}>
              <Text style={[styles.statusText, isLive && styles.statusTextLive]}>
                {statusLabel(match.status, match.minute)}
              </Text>
            </View>
          </View>
          <View style={styles.teamCol}>
            <TeamBadge name={match.away_team.name} shortName={match.away_team.short_name} logoUrl={match.away_team.logo_url} size={48} />
            <Text style={styles.teamName} numberOfLines={1}>{match.away_team.name}</Text>
          </View>
        </View>
        <Text style={styles.meta}>
          {formatKickoffDate(match.kickoff_time)} · {formatKickoff(match.kickoff_time)} UTC
          {match.venue ? `  ·  ${match.venue}` : ""}
        </Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>Match Events</Text>
        {match.events.length === 0 ? (
          <EmptyState message="No events yet." />
        ) : (
          match.events.map((event) => {
            const isHome = event.team?.id === match.home_team.id
            return (
              <View key={event.id} style={styles.eventRow}>
                <Text style={styles.eventMinute}>{event.minute}&apos;</Text>
                <Ionicons
                  name={
                    event.event_type === "yellow_card" || event.event_type === "red_card"
                      ? "square"
                      : event.event_type === "substitution"
                        ? "swap-horizontal"
                        : "football"
                  }
                  size={14}
                  color={
                    event.event_type === "yellow_card"
                      ? theme.amber
                      : event.event_type === "red_card"
                        ? theme.red
                        : theme.emerald
                  }
                />
                <Text style={styles.eventText} numberOfLines={1}>
                  {isHome ? match.home_team.short_name ?? "H" : match.away_team.short_name ?? "A"} · {event.player?.name ?? "Unknown"}
                </Text>
              </View>
            )
          })
        )}
      </View>
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: theme.background,
  },
  content: {
    padding: 16,
    gap: 12,
  },
  headerRow: {
    marginBottom: 4,
    alignItems: "flex-end",
  },
  card: {
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    padding: 16,
    marginBottom: 12,
  },
  competition: {
    color: theme.textFaint,
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
    textAlign: "center",
    marginBottom: 16,
  },
  scoreRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  teamCol: {
    flex: 1,
    alignItems: "center",
    gap: 8,
  },
  teamName: {
    color: theme.text,
    fontSize: 12,
    fontWeight: "600",
    textAlign: "center",
  },
  scoreCol: {
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 8,
  },
  score: {
    color: theme.text,
    fontSize: 28,
    fontWeight: "800",
  },
  statusPill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
  },
  statusPillLive: {
    backgroundColor: "rgba(52,211,153,0.15)",
  },
  statusText: {
    color: theme.textFaint,
    fontSize: 11,
    fontWeight: "700",
  },
  statusTextLive: {
    color: theme.emerald,
  },
  meta: {
    color: theme.textFaint,
    fontSize: 11,
    textAlign: "center",
    marginTop: 16,
  },
  sectionTitle: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "700",
    marginBottom: 12,
  },
  eventRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 6,
  },
  eventMinute: {
    color: theme.textFaint,
    fontSize: 11,
    fontWeight: "700",
    width: 28,
  },
  eventText: {
    color: theme.textMuted,
    fontSize: 13,
    flex: 1,
  },
})
