import { Link, useLocalSearchParams } from "expo-router"
import { useCallback, useEffect, useState } from "react"
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native"
import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { FavouriteButton } from "@/components/favourite-button"
import { LoadingState } from "@/components/loading-state"
import { MatchCard } from "@/components/match-card"
import { TeamBadge } from "@/components/team-badge"
import { useAuth } from "@/hooks/use-auth"
import { api, ApiError } from "@/lib/api"
import { theme } from "@/theme"
import type { CompetitionOut, MatchSummary, StandingEntry } from "@/types/api"

export default function CompetitionScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const { user } = useAuth()
  const [competition, setCompetition] = useState<CompetitionOut | null>(null)
  const [fixtures, setFixtures] = useState<MatchSummary[]>([])
  const [standings, setStandings] = useState<StandingEntry[]>([])
  const [initialFollowed, setInitialFollowed] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const competitionId = Number(id)
      const [comp, fixturesPage, standingsList, favourites] = await Promise.all([
        api.getCompetition(competitionId),
        api.getCompetitionFixtures(competitionId),
        api.getStandings(competitionId),
        user ? api.getFavourites().catch(() => null) : Promise.resolve(null),
      ])
      setCompetition(comp)
      setFixtures(fixturesPage.items)
      setStandings(standingsList)
      setInitialFollowed(favourites?.competitions.some((f) => f.competition.id === competitionId) ?? false)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "Competition not found." : "Unable to load this competition.")
    } finally {
      setLoading(false)
    }
  }, [id, user])

  useEffect(() => {
    const handle = setTimeout(load, 0)
    return () => clearTimeout(handle)
  }, [load])

  if (loading) {
    return (
      <View style={styles.screen}>
        <LoadingState label="Loading competition…" />
      </View>
    )
  }

  if (error || !competition) {
    return (
      <View style={styles.screen}>
        <ErrorState message={error ?? "Unable to load this competition."} onRetry={load} />
      </View>
    )
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.headerCard}>
        <TeamBadge name={competition.name} logoUrl={competition.logo_url} size={44} />
        <View style={{ flex: 1 }}>
          <Text style={styles.headerTitle}>{competition.name}</Text>
          <Text style={styles.headerSubtitle}>
            {competition.country ?? "International"} · {competition.type}
          </Text>
        </View>
        <FavouriteButton kind="competition" id={competition.id} initialFollowed={initialFollowed} />
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>Fixtures</Text>
        {fixtures.length === 0 ? (
          <EmptyState message="No fixtures available." />
        ) : (
          fixtures.map((match) => <MatchCard key={match.id} match={match} />)
        )}
      </View>

      {standings.length > 0 && (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Standings</Text>
          <View style={styles.standingsHeader}>
            <Text style={[styles.standingsHeaderText, styles.posCol]}>#</Text>
            <Text style={[styles.standingsHeaderText, styles.teamCol]}>Team</Text>
            <Text style={[styles.standingsHeaderText, styles.numCol]}>P</Text>
            <Text style={[styles.standingsHeaderText, styles.numCol]}>GD</Text>
            <Text style={[styles.standingsHeaderText, styles.numCol]}>Pts</Text>
          </View>
          {standings.map((row) => (
            <Link key={row.team.id} href={{ pathname: "/team/[id]", params: { id: String(row.team.id) } }} asChild>
              <Pressable style={styles.standingsRow}>
                <Text style={[styles.standingsText, styles.posCol]}>{row.position}</Text>
                <View style={[styles.teamCol, styles.teamCell]}>
                  <TeamBadge name={row.team.name} shortName={row.team.short_name} logoUrl={row.team.logo_url} size={20} />
                  <Text style={styles.standingsText} numberOfLines={1}>{row.team.name}</Text>
                </View>
                <Text style={[styles.standingsText, styles.numCol]}>{row.played}</Text>
                <Text style={[styles.standingsText, styles.numCol]}>{row.goals_for - row.goals_against}</Text>
                <Text style={[styles.standingsText, styles.numCol, styles.points]}>{row.points}</Text>
              </Pressable>
            </Link>
          ))}
        </View>
      )}
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
  headerCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    padding: 16,
    marginBottom: 12,
  },
  headerTitle: {
    color: theme.text,
    fontSize: 16,
    fontWeight: "700",
  },
  headerSubtitle: {
    color: theme.textFaint,
    fontSize: 11,
    marginTop: 2,
  },
  card: {
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    padding: 12,
    marginBottom: 12,
  },
  sectionTitle: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "700",
    marginBottom: 8,
    paddingHorizontal: 4,
  },
  standingsHeader: {
    flexDirection: "row",
    paddingHorizontal: 4,
    paddingVertical: 6,
  },
  standingsHeaderText: {
    color: theme.textFaint,
    fontSize: 10,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  standingsRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 4,
    paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.border,
  },
  standingsText: {
    color: theme.textMuted,
    fontSize: 12,
  },
  posCol: {
    width: 22,
  },
  teamCol: {
    flex: 1,
  },
  teamCell: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  numCol: {
    width: 32,
    textAlign: "center",
  },
  points: {
    color: theme.text,
    fontWeight: "700",
  },
})
