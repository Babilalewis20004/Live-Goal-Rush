import { Ionicons } from "@expo/vector-icons"
import { Link, router } from "expo-router"
import { useEffect, useState } from "react"
import { Keyboard, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native"

import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { LoadingState } from "@/components/loading-state"
import { MatchCard } from "@/components/match-card"
import { ArticleCard } from "@/components/news/article-card"
import { TeamBadge } from "@/components/team-badge"
import { useRecentSearches } from "@/hooks/use-recent-searches"
import { api, ApiError } from "@/lib/api"
import { normalizeSearch } from "@/lib/search-history"
import { theme } from "@/theme"
import type { SearchResults, SearchSuggestion } from "@/types/api"

const TYPE_LABEL: Record<SearchSuggestion["type"], string> = {
  team: "Team",
  player: "Player",
  competition: "Competition",
  article: "News",
}

function openSuggestion(s: SearchSuggestion) {
  switch (s.type) {
    case "team":
      router.push({ pathname: "/team/[id]", params: { id: String(s.id) } })
      break
    case "player":
      router.push({ pathname: "/player/[id]", params: { id: String(s.id) } })
      break
    case "competition":
      router.push({ pathname: "/competition/[id]", params: { id: String(s.id) } })
      break
    default:
      router.push({ pathname: "/article/[slug]", params: { slug: String(s.slug) } })
  }
}

export default function SearchScreen() {
  const [text, setText] = useState("")
  const [submitted, setSubmitted] = useState("")
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([])
  const [results, setResults] = useState<SearchResults | null>(null)
  const [popular, setPopular] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { recent, remember, forget, forgetAll } = useRecentSearches()

  const typed = normalizeSearch(text)

  useEffect(() => {
    const handle = setTimeout(() => {
      api.getPopularSearches().then((r) => setPopular(r.queries)).catch(() => {})
    }, 0)
    return () => clearTimeout(handle)
  }, [])

  // Suggestions as you type (state is only set from the timer callback, never
  // synchronously in the effect).
  useEffect(() => {
    let stale = false
    const handle = setTimeout(async () => {
      if (typed.length < 2) {
        setSuggestions([])
        return
      }
      try {
        const r = await api.getSearchSuggestions(typed)
        if (!stale) setSuggestions(r.suggestions)
      } catch {
        if (!stale) setSuggestions([])
      }
    }, 250)
    return () => {
      stale = true
      clearTimeout(handle)
    }
  }, [typed])

  async function runSearch(query: string) {
    const clean = normalizeSearch(query)
    if (!clean) return
    Keyboard.dismiss()
    setText(clean)
    setSubmitted(clean)
    setLoading(true)
    setError(null)
    remember(clean)
    try {
      setResults(await api.search(clean))
    } catch (e) {
      setResults(null)
      setError(
        e instanceof ApiError && e.status === 429
          ? "You're searching a little fast — wait a moment and try again."
          : "Unable to search right now.",
      )
    } finally {
      setLoading(false)
    }
  }

  function clear() {
    setText("")
    setSubmitted("")
    setResults(null)
    setError(null)
    setSuggestions([])
  }

  const showResults = submitted !== "" && typed === submitted
  const total = results
    ? results.teams.length + results.competitions.length + results.players.length + results.matches.length + results.articles.length
    : 0

  return (
    <View style={styles.screen}>
      <View style={styles.searchBar}>
        <Ionicons name="search" size={16} color={theme.textFaint} />
        <TextInput
          value={text}
          onChangeText={(v) => setText(v.slice(0, 100))}
          onSubmitEditing={() => void runSearch(text)}
          returnKeyType="search"
          accessibilityLabel="Search teams, players, competitions, matches and news"
          placeholder="Search teams, players, competitions, news…"
          placeholderTextColor={theme.textFaint}
          autoCorrect={false}
          autoCapitalize="none"
          maxLength={100}
          style={styles.input}
        />
        {text.length > 0 && (
          <Pressable accessibilityRole="button" accessibilityLabel="Clear search" onPress={clear} hitSlop={10} style={styles.clear}>
            <Ionicons name="close-circle" size={18} color={theme.textFaint} />
          </Pressable>
        )}
      </View>

      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        {/* nothing typed: recent + popular */}
        {typed === "" && (
          <View>
            {recent.length > 0 && (
              <View style={styles.section}>
                <View style={styles.sectionHead}>
                  <Text style={styles.sectionTitle}>Recent searches</Text>
                  <Pressable accessibilityRole="button" accessibilityLabel="Clear all recent searches" onPress={forgetAll} hitSlop={8}>
                    <Text style={styles.link}>Clear all</Text>
                  </Pressable>
                </View>
                {recent.map((q) => (
                  <View key={q} style={styles.recentRow}>
                    <Pressable accessibilityRole="button" accessibilityLabel={`Search ${q}`} onPress={() => void runSearch(q)} style={{ flex: 1 }}>
                      <Text style={styles.rowText}>{q}</Text>
                    </Pressable>
                    <Pressable accessibilityRole="button" accessibilityLabel={`Remove ${q} from recent searches`} onPress={() => forget(q)} hitSlop={10}>
                      <Ionicons name="close" size={16} color={theme.textFaint} />
                    </Pressable>
                  </View>
                ))}
              </View>
            )}
            {popular.length > 0 && (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Popular searches</Text>
                <View style={styles.chips}>
                  {popular.map((q) => (
                    <Pressable key={q} accessibilityRole="button" accessibilityLabel={`Search ${q}`} onPress={() => void runSearch(q)} style={styles.chip}>
                      <Text style={styles.chipText}>{q}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            )}
            <EmptyState message="Search for teams, players, competitions, matches or news." />
          </View>
        )}

        {/* typing: suggestions */}
        {typed.length >= 2 && !showResults && (
          <View style={styles.section}>
            {suggestions.map((s) => (
              <Pressable
                key={`${s.type}-${s.id}`}
                accessibilityRole="button"
                accessibilityLabel={`${TYPE_LABEL[s.type]}: ${s.label}`}
                onPress={() => {
                  remember(typed)
                  api.trackSearch(typed, s.type, s.id).catch(() => {})
                  openSuggestion(s)
                }}
                style={styles.row}
              >
                <Text style={styles.rowText} numberOfLines={1}>
                  {s.label}
                </Text>
                <Text style={styles.position}>{TYPE_LABEL[s.type]}</Text>
              </Pressable>
            ))}
            <Pressable accessibilityRole="button" onPress={() => void runSearch(typed)} style={styles.row}>
              <Text style={styles.rowText}>See all results for &ldquo;{typed}&rdquo;</Text>
              <Ionicons name="arrow-forward" size={14} color={theme.textFaint} />
            </Pressable>
          </View>
        )}

        {typed.length === 1 && <EmptyState message="Keep typing — suggestions start at two letters." />}

        {/* submitted: grouped results */}
        {showResults && loading && <LoadingState label="Searching…" />}
        {showResults && !loading && error && <ErrorState message={error} onRetry={() => void runSearch(submitted)} />}
        {showResults && !loading && !error && results && total === 0 && (
          <EmptyState message={`No results for "${submitted}". Check the spelling or try a shorter name.`} />
        )}

        {showResults && !loading && results && results.teams.length > 0 && (
          <View style={styles.section}>
            <Text accessibilityRole="header" style={styles.sectionTitle}>
              Teams
            </Text>
            {results.teams.map((team) => (
              <Link key={team.id} href={{ pathname: "/team/[id]", params: { id: String(team.id) } }} asChild>
                <Pressable
                  accessibilityRole="link"
                  style={styles.row}
                  onPress={() => api.trackSearch(submitted, "team", team.id).catch(() => {})}
                >
                  <TeamBadge name={team.name} shortName={team.short_name} logoUrl={team.logo_url} />
                  <Text style={styles.rowText}>{team.name}</Text>
                </Pressable>
              </Link>
            ))}
          </View>
        )}

        {showResults && !loading && results && results.players.length > 0 && (
          <View style={styles.section}>
            <Text accessibilityRole="header" style={styles.sectionTitle}>
              Players
            </Text>
            {results.players.map((player) => (
              <Link key={player.id} href={{ pathname: "/player/[id]", params: { id: String(player.id) } }} asChild>
                <Pressable
                  accessibilityRole="link"
                  style={styles.row}
                  onPress={() => api.trackSearch(submitted, "player", player.id).catch(() => {})}
                >
                  <Text style={styles.rowText}>{player.name}</Text>
                  {player.position && <Text style={styles.position}>{player.position}</Text>}
                </Pressable>
              </Link>
            ))}
          </View>
        )}

        {showResults && !loading && results && results.competitions.length > 0 && (
          <View style={styles.section}>
            <Text accessibilityRole="header" style={styles.sectionTitle}>
              Competitions
            </Text>
            {results.competitions.map((competition) => (
              <Link key={competition.id} href={{ pathname: "/competition/[id]", params: { id: String(competition.id) } }} asChild>
                <Pressable
                  accessibilityRole="link"
                  style={styles.row}
                  onPress={() => api.trackSearch(submitted, "competition", competition.id).catch(() => {})}
                >
                  <TeamBadge name={competition.name} logoUrl={competition.logo_url} />
                  <Text style={styles.rowText}>{competition.name}</Text>
                </Pressable>
              </Link>
            ))}
          </View>
        )}

        {showResults && !loading && results && results.articles.length > 0 && (
          <View style={styles.section}>
            <Text accessibilityRole="header" style={styles.sectionTitle}>
              News
            </Text>
            {results.articles.map((article) => (
              <ArticleCard key={article.id} article={article} />
            ))}
          </View>
        )}

        {showResults && !loading && results && results.matches.length > 0 && (
          <View style={styles.section}>
            <Text accessibilityRole="header" style={styles.sectionTitle}>
              Matches
            </Text>
            {results.matches.map((match) => (
              <MatchCard key={match.id} match={match} />
            ))}
          </View>
        )}
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.background },
  searchBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    margin: 16,
    marginBottom: 0,
    paddingHorizontal: 14,
    minHeight: 46,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
  },
  input: { flex: 1, color: theme.text, fontSize: 14, paddingVertical: 10 },
  clear: { minWidth: 32, minHeight: 32, alignItems: "center", justifyContent: "center" },
  content: { padding: 16, paddingBottom: 48 },
  section: { marginBottom: 16 },
  sectionHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  sectionTitle: { color: theme.textFaint, fontSize: 11, fontWeight: "700", textTransform: "uppercase", marginBottom: 8 },
  link: { color: theme.textMuted, fontSize: 12 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    padding: 12,
    minHeight: 48,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    marginBottom: 8,
  },
  recentRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 12,
    minHeight: 44,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    marginBottom: 8,
  },
  rowText: { color: theme.text, fontSize: 14, flex: 1 },
  position: { color: theme.textFaint, fontSize: 11 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    minHeight: 36,
    paddingHorizontal: 14,
    justifyContent: "center",
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
  },
  chipText: { color: theme.textMuted, fontSize: 13 },
})
