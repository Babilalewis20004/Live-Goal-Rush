import { Link, router } from "expo-router"
import { useEffect, useState } from "react"
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native"

import { EmptyState } from "@/components/empty-state"
import { LoadingState } from "@/components/loading-state"
import { useAuth } from "@/hooks/use-auth"
import { ApiError, api } from "@/lib/api"
import { formatArticleDate } from "@/lib/news"
import { theme } from "@/theme"
import type { ArticleAdminSummary, ArticleStatus } from "@/types/api"

export const STATUS_LABEL: Record<ArticleStatus, string> = {
  draft: "Draft",
  in_review: "In review",
  scheduled: "Scheduled",
  published: "Published",
  archived: "Archived",
}

const FILTERS: { id: ArticleStatus | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "draft", label: "Drafts" },
  { id: "in_review", label: "In review" },
  { id: "scheduled", label: "Scheduled" },
  { id: "published", label: "Published" },
  { id: "archived", label: "Archived" },
]

/** The writer's / editor's desk. Authors see their own articles; editors their own
 * plus everything past draft (so "In review" is the review queue); admins see all. */
export default function EditorHome() {
  const { user, loading: authLoading } = useAuth()
  const allowed = user?.role === "author" || user?.role === "editor" || user?.role === "admin"
  const reviewer = user?.role === "editor" || user?.role === "admin"
  const [filter, setFilter] = useState<ArticleStatus | "all">(reviewer ? "in_review" : "all")
  const [items, setItems] = useState<ArticleAdminSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (authLoading || !allowed) return
    let cancelled = false
    const handle = setTimeout(async () => {
      try {
        const page = await api.listEditorArticles(filter === "all" ? undefined : filter)
        if (!cancelled) {
          setItems(page.items)
          setError(null)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Couldn't load articles.")
      }
    }, 0)
    return () => {
      cancelled = true
      clearTimeout(handle)
    }
  }, [filter, authLoading, allowed])

  if (authLoading) return <View style={styles.screen}><LoadingState label="Loading…" /></View>
  if (!allowed) {
    return (
      <View style={styles.screen}>
        <EmptyState message="This area is for writers and editors." />
      </View>
    )
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Pressable accessibilityRole="button" onPress={() => router.push("/editor/new")} style={styles.primary}>
        <Text style={styles.primaryText}>New article</Text>
      </Pressable>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips} accessibilityRole="tablist">
        {FILTERS.map((f) => {
          const selected = filter === f.id
          return (
            <Pressable
              key={f.id}
              accessibilityRole="tab"
              accessibilityState={{ selected }}
              onPress={() => {
                setItems(null)
                setFilter(f.id)
              }}
              style={[styles.chip, selected && styles.chipOn]}
            >
              <Text style={[styles.chipText, selected && styles.chipTextOn]}>{f.label}</Text>
            </Pressable>
          )
        })}
      </ScrollView>

      {error ? (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      ) : items === null ? (
        <LoadingState label="Loading articles…" />
      ) : items.length === 0 ? (
        <EmptyState message={filter === "in_review" ? "Nothing is waiting for review." : "No articles here yet."} />
      ) : (
        items.map((a) => (
          <Link key={a.id} href={{ pathname: "/editor/[id]", params: { id: String(a.id) } }} asChild>
            <Pressable
              accessibilityRole="link"
              accessibilityLabel={`${a.title}. ${STATUS_LABEL[a.status]}${a.author_name ? `, by ${a.author_name}` : ""}`}
              style={styles.row}
            >
              <Text style={styles.title} numberOfLines={2}>
                {a.title}
              </Text>
              <Text style={styles.meta}>
                {STATUS_LABEL[a.status]}
                {a.published_at ? ` · ${formatArticleDate(a.published_at)}` : ""}
                {a.author_name ? ` · by ${a.author_name}` : ""}
              </Text>
            </Pressable>
          </Link>
        ))
      )}
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.background },
  content: { padding: 16, gap: 12, paddingBottom: 48 },
  primary: { minHeight: 48, borderRadius: 12, backgroundColor: theme.emerald, alignItems: "center", justifyContent: "center" },
  primaryText: { color: theme.background, fontWeight: "700", fontSize: 14 },
  chips: { gap: 8 },
  chip: { minHeight: 36, paddingHorizontal: 14, justifyContent: "center", borderRadius: 999, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, backgroundColor: theme.card },
  chipOn: { backgroundColor: theme.emerald, borderColor: theme.emerald },
  chipText: { color: theme.textMuted, fontSize: 13, fontWeight: "600" },
  chipTextOn: { color: theme.background },
  row: { padding: 14, borderRadius: 14, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, backgroundColor: theme.card, gap: 4, minHeight: 56 },
  title: { color: theme.text, fontSize: 14, fontWeight: "600" },
  meta: { color: theme.textFaint, fontSize: 12 },
  error: { color: "#fca5a5", fontSize: 13 },
})
