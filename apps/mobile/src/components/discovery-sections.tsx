import { Link } from "expo-router"
import { useEffect, useState } from "react"
import { Pressable, StyleSheet, Text, View } from "react-native"

import { MatchCard } from "@/components/match-card"
import { ArticleCard } from "@/components/news/article-card"
import { TeamBadge } from "@/components/team-badge"
import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import { trendLabel } from "@/lib/news"
import { theme } from "@/theme"
import type { DiscoveryHome, FeedOut } from "@/types/api"

/** Loads once, fails soft: discovery is additive, so an error simply renders
 * nothing and the scoreboard above is unaffected. */
function useLoaded<T>(load: (() => Promise<T>) | null): T | null {
  const [value, setValue] = useState<T | null>(null)
  useEffect(() => {
    if (!load) return
    let cancelled = false
    const handle = setTimeout(() => {
      load()
        .then((v) => !cancelled && setValue(v))
        .catch(() => {})
    }, 0)
    return () => {
      cancelled = true
      clearTimeout(handle)
    }
    // `load` is a stable module-level function
  }, [load])
  return value
}

const loadHome = () => api.getDiscoveryHome()
const loadFeed = () => api.getFeed()

/** "For you": the signed-in user's feed (deterministic tiers, each item with
 * the reason it is there). Nothing for anonymous users or if they follow nothing. */
export function ForYou() {
  const { user } = useAuth()
  const feed: FeedOut | null = useLoaded(user ? loadFeed : null)
  if (!user || !feed || !feed.personalised || feed.items.length === 0) return null
  const items = feed.items.filter((i) => i.reason !== "trending")
  if (items.length === 0) return null

  return (
    <View style={styles.section}>
      <Text accessibilityRole="header" style={styles.title}>
        For you
      </Text>
      {items.slice(0, 8).map((item) => (
        <View key={`${item.kind}-${item.match?.id ?? item.article?.id}`} style={{ marginBottom: 10 }}>
          {item.kind === "match" && item.match ? <MatchCard match={item.match} /> : null}
          {item.kind === "article" && item.article ? <ArticleCard article={item.article} /> : null}
          <Text style={styles.explain}>{item.explanation}</Text>
        </View>
      ))}
    </View>
  )
}

/** News, trending and popular competitions, from the public cached
 * `/discovery/home` payload. A section with no data is not rendered. */
export function DiscoverySections() {
  const home: DiscoveryHome | null = useLoaded(loadHome)
  if (!home) return null
  const lead = home.featured_articles[0] ?? home.latest_articles[0]
  const more = home.latest_articles.filter((a) => a.id !== lead?.id).slice(0, 3)

  return (
    <View>
      {lead ? (
        <View style={styles.section}>
          <Text accessibilityRole="header" style={styles.title}>
            Football news
          </Text>
          <ArticleCard article={lead} />
          {more.map((a) => (
            <ArticleCard key={a.id} article={a} compact />
          ))}
        </View>
      ) : null}

      {home.trending_teams.length > 0 ? (
        <View style={styles.section}>
          <Text accessibilityRole="header" style={styles.title}>
            Trending teams
          </Text>
          {home.trending_teams.slice(0, 5).map(({ item, signals }) => (
            <Link key={item.id} href={{ pathname: "/team/[id]", params: { id: String(item.id) } }} asChild>
              <Pressable accessibilityRole="link" accessibilityLabel={`${item.name}. ${trendLabel(signals)}`} style={styles.row}>
                <TeamBadge name={item.name} shortName={item.short_name} logoUrl={item.logo_url} size={28} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{item.name}</Text>
                  <Text style={styles.rowSub}>{trendLabel(signals)}</Text>
                </View>
              </Pressable>
            </Link>
          ))}
        </View>
      ) : null}

      {home.trending_players.length > 0 ? (
        <View style={styles.section}>
          <Text accessibilityRole="header" style={styles.title}>
            Trending players
          </Text>
          {home.trending_players.slice(0, 5).map(({ item, signals }) => (
            <Link key={item.id} href={{ pathname: "/player/[id]", params: { id: String(item.id) } }} asChild>
              <Pressable accessibilityRole="link" accessibilityLabel={`${item.name}. ${trendLabel(signals)}`} style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{item.name}</Text>
                  <Text style={styles.rowSub}>{trendLabel(signals)}</Text>
                </View>
                {item.position ? <Text style={styles.rowSub}>{item.position}</Text> : null}
              </Pressable>
            </Link>
          ))}
        </View>
      ) : null}

      {home.popular_competitions.length > 0 ? (
        <View style={styles.section}>
          <Text accessibilityRole="header" style={styles.title}>
            Popular competitions
          </Text>
          {home.popular_competitions.slice(0, 6).map((c) => (
            <Link key={c.id} href={{ pathname: "/competition/[id]", params: { id: String(c.id) } }} asChild>
              <Pressable accessibilityRole="link" accessibilityLabel={c.name} style={styles.row}>
                <TeamBadge name={c.name} logoUrl={c.logo_url} size={28} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{c.name}</Text>
                  <Text style={styles.rowSub}>{c.country ?? "International"}</Text>
                </View>
              </Pressable>
            </Link>
          ))}
        </View>
      ) : null}
    </View>
  )
}

const styles = StyleSheet.create({
  section: { marginTop: 24 },
  title: { color: theme.text, fontSize: 15, fontWeight: "700", marginBottom: 10 },
  explain: { color: theme.textFaint, fontSize: 11, marginTop: 4, paddingHorizontal: 4 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    minHeight: 52,
    padding: 12,
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    marginBottom: 8,
  },
  rowTitle: { color: theme.text, fontSize: 14, fontWeight: "600" },
  rowSub: { color: theme.textFaint, fontSize: 11, marginTop: 1 },
})
