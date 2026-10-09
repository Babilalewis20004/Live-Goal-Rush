import { useState } from "react"
import { Pressable, StyleSheet, Text, View } from "react-native"

import { EmptyState } from "@/components/empty-state"
import { ArticleCard } from "@/components/news/article-card"
import { api } from "@/lib/api"
import { theme } from "@/theme"
import type { ArticleSummary, Page } from "@/types/api"

type Kind = "team" | "player" | "competition" | "match"

const LOADERS: Record<Kind, (id: number, page: number) => Promise<Page<ArticleSummary>>> = {
  team: (id, page) => api.getTeamNews(id, page),
  player: (id, page) => api.getPlayerNews(id, page),
  competition: (id, page) => api.getCompetitionNews(id, page),
  match: (id, page) => api.getMatchNews(id, page),
}

/** The News tab/section on team, player, competition and match screens: the
 * first page comes with the screen's own load, later pages on demand. Only
 * articles explicitly linked to this entity are ever listed (the API
 * guarantees it), so an empty list is shown as empty. */
export function EntityNews({ kind, id, initial }: { kind: Kind; id: number; initial: Page<ArticleSummary> }) {
  const [items, setItems] = useState(initial.items)
  const [page, setPage] = useState(initial.page)
  const [total, setTotal] = useState(initial.total)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (items.length === 0) return <EmptyState message="No news linked to this yet." />

  async function more() {
    setLoading(true)
    setError(null)
    try {
      const next = await LOADERS[kind](id, page + 1)
      setItems((current) => [...current, ...next.items.filter((a) => !current.some((c) => c.id === a.id))])
      setPage(next.page)
      setTotal(next.total)
    } catch {
      setError("Couldn't load more news. Try again.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <View>
      {items.map((article) => (
        <ArticleCard key={article.id} article={article} />
      ))}
      {error ? (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      ) : null}
      {items.length < total ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Load ${total - items.length} more articles`}
          onPress={more}
          disabled={loading}
          style={[styles.more, loading && { opacity: 0.6 }]}
        >
          <Text style={styles.moreText}>{loading ? "Loading…" : `Load more (${total - items.length})`}</Text>
        </Pressable>
      ) : null}
    </View>
  )
}

const styles = StyleSheet.create({
  error: { color: "#fca5a5", fontSize: 12, marginBottom: 8 },
  more: {
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
  },
  moreText: { color: theme.textMuted, fontSize: 13, fontWeight: "600" },
})
