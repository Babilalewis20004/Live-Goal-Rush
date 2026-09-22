import { useLocalSearchParams } from "expo-router"
import { useCallback, useEffect, useState } from "react"
import { ScrollView, StyleSheet, Text, View } from "react-native"
import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { FavouriteButton } from "@/components/favourite-button"
import { LoadingState } from "@/components/loading-state"
import { MatchCard } from "@/components/match-card"
import { TeamBadge } from "@/components/team-badge"
import { useAuth } from "@/hooks/use-auth"
import { api, ApiError } from "@/lib/api"
import { theme } from "@/theme"
import type { MatchSummary, TeamOut } from "@/types/api"

export default function TeamScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const { user } = useAuth()
  const [team, setTeam] = useState<TeamOut | null>(null)
  const [fixtures, setFixtures] = useState<MatchSummary[]>([])
  const [results, setResults] = useState<MatchSummary[]>([])
  const [initialFollowed, setInitialFollowed] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const teamId = Number(id)
      const [teamData, fixturesPage, resultsPage, favourites] = await Promise.all([
        api.getTeam(teamId),
        api.getTeamFixtures(teamId),
        api.getTeamResults(teamId),
        user ? api.getFavourites().catch(() => null) : Promise.resolve(null),
      ])
      setTeam(teamData)
      setFixtures(fixturesPage.items)
      setResults(resultsPage.items)
      setInitialFollowed(favourites?.teams.some((f) => f.team.id === teamId) ?? false)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "Team not found." : "Unable to load this team.")
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
        <LoadingState label="Loading team…" />
      </View>
    )
  }

  if (error || !team) {
    return (
      <View style={styles.screen}>
        <ErrorState message={error ?? "Unable to load this team."} onRetry={load} />
      </View>
    )
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.headerCard}>
        <TeamBadge name={team.name} shortName={team.short_name} logoUrl={team.logo_url} size={44} />
        <View style={{ flex: 1 }}>
          <Text style={styles.headerTitle}>{team.name}</Text>
          {team.country && <Text style={styles.headerSubtitle}>{team.country}</Text>}
        </View>
        <FavouriteButton kind="team" id={team.id} initialFollowed={initialFollowed} />
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>Upcoming Fixtures</Text>
        {fixtures.length === 0 ? (
          <EmptyState message="No upcoming fixtures." />
        ) : (
          fixtures.map((match) => <MatchCard key={match.id} match={match} />)
        )}
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>Recent Results</Text>
        {results.length === 0 ? (
          <EmptyState message="No recent results." />
        ) : (
          results.map((match) => <MatchCard key={match.id} match={match} />)
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
})
