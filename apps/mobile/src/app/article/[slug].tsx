import { Image } from "expo-image"
import { Link, Stack, useLocalSearchParams } from "expo-router"
import { useCallback, useEffect, useState } from "react"
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native"

import { ErrorState } from "@/components/error-state"
import { LoadingState } from "@/components/loading-state"
import { MatchCard } from "@/components/match-card"
import { ArticleCard } from "@/components/news/article-card"
import { Discuss } from "@/components/community/discuss"
import { ArticleBlocks } from "@/components/news/article-blocks"
import { Gallery } from "@/components/news/gallery"
import { ShareButton } from "@/components/news/share-button"
import { api, ApiError } from "@/lib/api"
import { formatArticleDate } from "@/lib/news"
import { theme } from "@/theme"
import type { ArticleDetail, ArticleSummary } from "@/types/api"

function Chip({ label, onPress, href }: { label: string; href: Parameters<typeof Link>[0]["href"]; onPress?: () => void }) {
  return (
    <Link href={href} asChild>
      <Pressable accessibilityRole="link" accessibilityLabel={label} onPress={onPress} style={styles.chip}>
        <Text style={styles.chipText}>{label}</Text>
      </Pressable>
    </Link>
  )
}

export default function ArticleScreen() {
  const { slug } = useLocalSearchParams<{ slug: string }>()
  const [article, setArticle] = useState<ArticleDetail | null>(null)
  const [related, setRelated] = useState<ArticleSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const loaded = await api.getArticle(String(slug))
      setArticle(loaded)
      setRelated(await api.getRelatedArticles(String(slug)).catch(() => []))
      // One fire-and-forget count per open; the API de-duplicates repeats.
      api.trackView("article", String(slug)).catch(() => {})
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "This article isn't available." : "Unable to load this article.")
    } finally {
      setLoading(false)
    }
  }, [slug])

  useEffect(() => {
    const handle = setTimeout(load, 0)
    return () => clearTimeout(handle)
  }, [load])

  if (loading) {
    return (
      <View style={styles.screen}>
        <LoadingState label="Loading article…" />
      </View>
    )
  }
  if (error || !article) {
    return (
      <View style={styles.screen}>
        <ErrorState message={error ?? "Unable to load this article."} onRetry={load} />
      </View>
    )
  }

  const hasEntities = article.teams.length + article.players.length + article.competitions.length > 0

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: article.category?.name ?? "News" }} />

      {article.category ? <Text style={styles.kicker}>{article.category.name}</Text> : null}
      <Text accessibilityRole="header" style={styles.title}>
        {article.title}
      </Text>
      <Text style={styles.meta}>
        {[formatArticleDate(article.published_at), article.author_name ? `By ${article.author_name}` : null]
          .filter(Boolean)
          .join(" · ")}
      </Text>
      <View style={{ marginTop: 12 }}>
        <ShareButton kind="article" id={article.slug} title={article.title} label="Share article" />
      </View>

      {article.featured_image_url ? (
        <Image
          source={{ uri: article.featured_image_url }}
          accessibilityLabel={article.featured_image_alt || article.title}
          accessible
          style={styles.image}
          contentFit="cover"
        />
      ) : null}

      {article.excerpt ? <Text style={styles.excerpt}>{article.excerpt}</Text> : null}
      <View style={{ marginTop: 8 }}>
        <ArticleBlocks blocks={article.content_blocks} fallback={article.content_text} />
      </View>

      <Gallery images={article.gallery} />

      {article.tags.length > 0 ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Tags</Text>
          <View style={styles.chips}>
            {article.tags.map((tag) => (
              <View key={tag.id} style={styles.chip} accessibilityLabel={`Tag ${tag.name}`}>
                <Text style={styles.chipText}>#{tag.name}</Text>
              </View>
            ))}
          </View>
        </View>
      ) : null}

      {hasEntities ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>In this story</Text>
          <View style={styles.chips}>
            {article.teams.map((t) => (
              <Chip key={`t${t.id}`} label={t.name} href={{ pathname: "/team/[id]", params: { id: String(t.id) } }} />
            ))}
            {article.players.map((p) => (
              <Chip key={`p${p.id}`} label={p.name} href={{ pathname: "/player/[id]", params: { id: String(p.id) } }} />
            ))}
            {article.competitions.map((c) => (
              <Chip key={`c${c.id}`} label={c.name} href={{ pathname: "/competition/[id]", params: { id: String(c.id) } }} />
            ))}
          </View>
        </View>
      ) : null}

      {article.matches.length > 0 ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Related matches</Text>
          {article.matches.map((m) => (
            <MatchCard key={m.id} match={m} />
          ))}
        </View>
      ) : null}

      <View style={styles.section} accessibilityLabel="Reactions and comments">
        <Discuss targetType="article" targetId={article.id} />
      </View>

      {related.length > 0 ? (
        <View style={styles.section}>
          <Text accessibilityRole="header" style={styles.sectionTitle}>
            Related articles
          </Text>
          {related.map((r) => (
            <ArticleCard key={r.id} article={r} />
          ))}
        </View>
      ) : null}
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.background },
  content: { padding: 16, paddingBottom: 56 },
  kicker: { color: theme.emerald, fontSize: 11, fontWeight: "700", textTransform: "uppercase" },
  title: { color: theme.text, fontSize: 24, fontWeight: "700", lineHeight: 30, marginTop: 4 },
  meta: { color: theme.textFaint, fontSize: 12, marginTop: 6 },
  image: { width: "100%", aspectRatio: 16 / 9, borderRadius: 14, marginTop: 16, backgroundColor: "rgba(255,255,255,0.05)" },
  excerpt: { color: theme.text, fontSize: 16, fontWeight: "500", lineHeight: 23, marginTop: 16 },
  section: { marginTop: 24 },
  sectionTitle: { color: theme.textFaint, fontSize: 11, fontWeight: "700", textTransform: "uppercase", marginBottom: 8 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    minHeight: 36,
    paddingHorizontal: 12,
    justifyContent: "center",
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
  },
  chipText: { color: theme.textMuted, fontSize: 12 },
})
