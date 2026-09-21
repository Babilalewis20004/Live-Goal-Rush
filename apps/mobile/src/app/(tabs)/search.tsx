import { Ionicons } from "@expo/vector-icons"
import { Link } from "expo-router"
import { useEffect, useState } from "react"
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native"
import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { LoadingState } from "@/components/loading-state"
import { TeamBadge } from "@/components/team-badge"
import { api, ApiError } from "@/lib/api"
import { theme } from "@/theme"
import type { SearchResults } from "@/types/api"

export default function SearchScreen() {
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<SearchResults | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Everything lives inside the timer callback (a genuine macrotask, not
    // synchronous-in-effect) so this never trips react-hooks/set-state-in-effect.
    const trimmed = query.trim()
    const handle = setTimeout(async () => {
      if (!trimmed) {
        setResults(null)
        setError(null)
        setLoading(false)
        return
      }
      setLoading(true)
      try {
        setResults(await api.search(trimmed))
        setError(null)
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Unable to search right now.")
      } finally {
        setLoading(false)
      }
    }, 300)
    return () => clearTimeout(handle)
  }, [query])

  const hasQuery = query.trim().length > 0
  const hasResults = results && (results.teams.length > 0 || results.competitions.length > 0 || results.players.length > 0)

  return (
    <View style={styles.screen}>
      <View style={styles.searchBar}>
        <Ionicons name="search" size={16} color={theme.textFaint} />
        <TextInput
          value={query}
          onChangeText={setQuery}
          placeholder="Search teams, competitions, players…"
          placeholderTextColor={theme.textFaint}
          style={styles.input}
        />
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        {loading && <LoadingState label="Searching…" />}
        {!loading && error && <ErrorState message={error} />}
        {!loading && !error && !hasQuery && <EmptyState message="Search for teams, competitions or players." />}
        {!loading && !error && hasQuery && !hasResults && <EmptyState message={`No results for "${query}".`} />}

        {!loading && results && results.teams.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Teams</Text>
            {results.teams.map((team) => (
              <Link key={team.id} href={{ pathname: "/team/[id]", params: { id: String(team.id) } }} asChild>
                <Pressable style={styles.row}>
                  <TeamBadge name={team.name} shortName={team.short_name} logoUrl={team.logo_url} />
                  <Text style={styles.rowText}>{team.name}</Text>
                </Pressable>
              </Link>
            ))}
          </View>
        )}

        {!loading && results && results.competitions.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Competitions</Text>
            {results.competitions.map((competition) => (
              <Link key={competition.id} href={{ pathname: "/competition/[id]", params: { id: String(competition.id) } }} asChild>
                <Pressable style={styles.row}>
                  <TeamBadge name={competition.name} logoUrl={competition.logo_url} />
                  <Text style={styles.rowText}>{competition.name}</Text>
                </Pressable>
              </Link>
            ))}
          </View>
        )}

        {!loading && results && results.players.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Players</Text>
            {results.players.map((player) => (
              <View key={player.id} style={styles.row}>
                <Text style={styles.rowText}>{player.name}</Text>
                {player.position && <Text style={styles.position}>{player.position}</Text>}
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: theme.background,
  },
  searchBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    margin: 16,
    marginBottom: 0,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
  },
  input: {
    flex: 1,
    color: theme.text,
    fontSize: 14,
  },
  content: {
    padding: 16,
  },
  section: {
    marginBottom: 16,
  },
  sectionTitle: {
    color: theme.textFaint,
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
    marginBottom: 8,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    padding: 12,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    marginBottom: 8,
  },
  rowText: {
    color: theme.text,
    fontSize: 14,
    flex: 1,
  },
  position: {
    color: theme.textFaint,
    fontSize: 11,
  },
})
