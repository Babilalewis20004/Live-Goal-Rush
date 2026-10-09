import { PlayerAnalytics } from "@/components/analytics/player-analytics"
import { Link, useLocalSearchParams } from "expo-router"
import { useCallback, useEffect, useState } from "react"
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native"
import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { LoadingState } from "@/components/loading-state"
import { EntityNews } from "@/components/news/entity-news"
import { ShareButton } from "@/components/news/share-button"
import { MatchCard } from "@/components/match-card"
import { Card, SectionTitle } from "@/components/match-centre/ui"
import { TeamBadge } from "@/components/team-badge"
import { api, ApiError } from "@/lib/api"
import { theme } from "@/theme"
import type {
  ArticleSummary,
  Capabilities,
  Page,
  PlayerDetail,
  PlayerMatchStatsOut,
  PlayerStatisticsOut,
} from "@/types/api"

function matchLine(stats: PlayerMatchStatsOut): string {
  // Only what the provider supplied: a null field is left out, never shown as 0.
  const parts: string[] = []
  if (stats.minutes_played != null) parts.push(`${stats.minutes_played} min`)
  if (stats.goals) parts.push(`${stats.goals} goal${stats.goals === 1 ? "" : "s"}`)
  if (stats.assists) parts.push(`${stats.assists} assist${stats.assists === 1 ? "" : "s"}`)
  if (stats.yellow_cards) parts.push(`${stats.yellow_cards} yellow`)
  if (stats.red_cards) parts.push("red card")
  return parts.join(" · ")
}

export default function PlayerScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const [player, setPlayer] = useState<PlayerDetail | null>(null)
  const [statistics, setStatistics] = useState<PlayerStatisticsOut | null>(null)
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [news, setNews] = useState<Page<ArticleSummary> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const playerId = Number(id)
      const [p, stats, caps, playerNews] = await Promise.all([
        api.getPlayer(playerId),
        api.getPlayerStatistics(playerId).catch(() => null),
        api.getCapabilities().catch(() => null),
        api.getPlayerNews(playerId).catch(() => null),
      ])
      setNews(playerNews)
      setPlayer(p)
      setStatistics(stats)
      setCapabilities(caps)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "Player not found." : "Unable to load this player.")
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
        <LoadingState label="Loading player…" />
      </View>
    )
  }

  if (error || !player) {
    return (
      <View style={styles.screen}>
        <ErrorState message={error ?? "Unable to load this player."} onRetry={load} />
      </View>
    )
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <ShareButton kind="player" id={player.id} title={player.name} />
      <View style={styles.headerCard}>
        <View style={styles.avatar} accessible={false}>
          <Text style={styles.avatarText}>{player.shirt_number ?? player.name.slice(0, 1)}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.title} accessibilityRole="header">
            {player.name}
          </Text>
          <Text style={styles.subtitle}>
            {[player.position, player.nationality].filter(Boolean).join(" · ") || "Profile details not available"}
          </Text>
        </View>
        {player.team && (
          <Link href={{ pathname: "/team/[id]", params: { id: String(player.team.id) } }} asChild>
            <Pressable accessibilityRole="link" accessibilityLabel={`Team: ${player.team.name}`} hitSlop={8}>
              <TeamBadge name={player.team.name} shortName={player.team.short_name} logoUrl={player.team.logo_url} size={32} />
            </Pressable>
          </Link>
        )}
      </View>
      {capabilities?.player_profiles === false && (
        <Text style={styles.faint}>Detailed player profiles aren&apos;t provided by the current football data provider.</Text>
      )}

      <Card>
        <SectionTitle>Season statistics</SectionTitle>
        {statistics && statistics.seasons.length > 0 ? (
          statistics.seasons.map((s) => (
            <View
              key={`${s.competition_id}-${s.season}`}
              style={styles.statRow}
              accessible
              accessibilityLabel={`${s.competition_name}, season ${s.season}: ${s.appearances ?? "unknown"} appearances, ${s.goals} goals${s.assists != null ? `, ${s.assists} assists` : ""}`}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.statName}>{s.competition_name}</Text>
                <Text style={styles.faint}>Season {s.season}</Text>
              </View>
              <Text style={styles.stat}>{s.appearances ?? "–"} apps</Text>
              <Text style={styles.stat}>{s.goals} gls</Text>
              <Text style={styles.stat}>{s.assists ?? "–"} ast</Text>
            </View>
          ))
        ) : (
          <EmptyState message="No season statistics are available for this player." />
        )}
      </Card>

      <PlayerAnalytics playerId={player.id} showSeasons={false} />

      <Card>
        <SectionTitle>Recent matches</SectionTitle>
        {statistics && statistics.recent_matches.length > 0 ? (
          statistics.recent_matches.map((a) => (
            <View key={a.match.id}>
              <MatchCard match={a.match} />
              {matchLine(a.stats) !== "" && <Text style={styles.matchLine}>{matchLine(a.stats)}</Text>}
            </View>
          ))
        ) : (
          <EmptyState message="No match statistics stored for this player yet." />
        )}
      </Card>
      {news && news.total > 0 ? (
        <Card>
          <SectionTitle>News</SectionTitle>
          <EntityNews kind="player" id={player.id} initial={news} />
        </Card>
      ) : null}
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.background },
  content: { padding: 16, gap: 12, paddingBottom: 48 },
  headerCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    padding: 16,
  },
  avatar: { width: 52, height: 52, borderRadius: 26, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(255,255,255,0.08)" },
  avatarText: { color: theme.textMuted, fontSize: 18, fontWeight: "800" },
  title: { color: theme.text, fontSize: 18, fontWeight: "800" },
  subtitle: { color: theme.textFaint, fontSize: 12, marginTop: 2 },
  faint: { color: theme.textFaint, fontSize: 11 },
  statRow: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 48 },
  statName: { color: theme.text, fontSize: 14 },
  stat: { color: theme.textMuted, fontSize: 12 },
  matchLine: { color: theme.textFaint, fontSize: 11, paddingLeft: 66, paddingBottom: 8 },
})
