import { useCallback, useEffect, useState } from "react"
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native"

import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { LoadingState } from "@/components/loading-state"
import { ArticleCard } from "@/components/news/article-card"
import { api, ApiError } from "@/lib/api"
import { theme } from "@/theme"
import type { ArticleSummary, CategoryOut } from "@/types/api"

const PAGE_SIZE = 12

export default function NewsScreen() {
  const [categories, setCategories] = useState<CategoryOut[]>([])
  const [category, setCategory] = useState<string | undefined>(undefined)
  const [articles, setArticles] = useState<ArticleSummary[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (slug: string | undefined) => {
    setError(null)
    try {
      const first = await api.getArticles({ page: 1, pageSize: PAGE_SIZE, category: slug })
      setArticles(first.items)
      setPage(1)
      setTotal(first.total)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unable to load the news.")
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    const handle = setTimeout(() => {
      api.getArticleCategories().then(setCategories).catch(() => {})
    }, 0)
    return () => clearTimeout(handle)
  }, [])

  useEffect(() => {
    const handle = setTimeout(() => void load(category), 0)
    return () => clearTimeout(handle)
  }, [category, load])

  async function more() {
    setLoadingMore(true)
    try {
      const next = await api.getArticles({ page: page + 1, pageSize: PAGE_SIZE, category })
      setArticles((current) => [...current, ...next.items.filter((a) => !current.some((c) => c.id === a.id))])
      setPage(next.page)
      setTotal(next.total)
    } catch {
      setError("Couldn't load more news.")
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => {
            setRefreshing(true)
            void load(category)
          }}
          tintColor={theme.emerald}
        />
      }
    >
      {categories.length > 0 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips} accessibilityRole="tablist">
          {[{ id: 0, slug: undefined as string | undefined, name: "All" }, ...categories].map((c) => {
            const selected = category === c.slug
            return (
              <Pressable
                key={c.id}
                accessibilityRole="tab"
                accessibilityState={{ selected }}
                accessibilityLabel={c.name}
                onPress={() => {
                  setLoading(true)
                  setCategory(c.slug)
                }}
                style={[styles.chip, selected && styles.chipActive]}
              >
                <Text style={[styles.chipText, selected && styles.chipTextActive]}>{c.name}</Text>
              </Pressable>
            )
          })}
        </ScrollView>
      ) : null}

      {loading ? (
        <LoadingState label="Loading news…" />
      ) : error && articles.length === 0 ? (
        <ErrorState message={error} onRetry={() => void load(category)} />
      ) : articles.length === 0 ? (
        <EmptyState message={category ? "No articles in this category yet." : "No news published yet."} />
      ) : (
        <View>
          {articles.map((article) => (
            <ArticleCard key={article.id} article={article} />
          ))}
          {error ? (
            <Text accessibilityRole="alert" style={styles.error}>
              {error}
            </Text>
          ) : null}
          {articles.length < total ? (
            <Pressable
              accessibilityRole="button"
              onPress={more}
              disabled={loadingMore}
              style={[styles.more, loadingMore && { opacity: 0.6 }]}
            >
              <Text style={styles.moreText}>{loadingMore ? "Loading…" : "Load more"}</Text>
            </Pressable>
          ) : null}
        </View>
      )}
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.background },
  content: { padding: 16, paddingBottom: 40 },
  chips: { gap: 8, paddingBottom: 14 },
  chip: {
    minHeight: 36,
    paddingHorizontal: 14,
    justifyContent: "center",
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
  },
  chipActive: { backgroundColor: theme.emerald, borderColor: theme.emerald },
  chipText: { color: theme.textMuted, fontSize: 13, fontWeight: "600" },
  chipTextActive: { color: theme.background },
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
