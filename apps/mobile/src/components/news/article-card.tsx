import { Image } from "expo-image"
import { Link } from "expo-router"
import { Pressable, StyleSheet, Text, View } from "react-native"

import { formatArticleDate, relationLabel } from "@/lib/news"
import { theme } from "@/theme"
import type { ArticleSummary } from "@/types/api"

/** One article in a list. The whole card is a single accessible link whose
 * label is the headline plus its meta, so a screen reader announces one
 * meaningful stop per article. State is always words (category, "About this
 * match"), never colour alone. */
export function ArticleCard({ article, compact = false }: { article: ArticleSummary; compact?: boolean }) {
  const relation = relationLabel(article.relation)
  const meta = [article.category?.name, formatArticleDate(article.published_at)].filter(Boolean).join(" · ")
  const kicker = relation ?? article.category?.name ?? "News"

  return (
    <Link href={{ pathname: "/article/[slug]", params: { slug: article.slug } }} asChild>
      <Pressable
        accessibilityRole="link"
        accessibilityLabel={`${article.title}. ${[relation, meta].filter(Boolean).join(", ")}`}
        style={({ pressed }) => [styles.card, compact && styles.compact, pressed && styles.pressed]}
      >
        {!compact && article.featured_image_url ? (
          <Image
            source={{ uri: article.featured_image_url }}
            // Decorative: the headline already names the story.
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            style={styles.image}
            contentFit="cover"
          />
        ) : null}
        <View style={styles.body}>
          {!compact && <Text style={styles.kicker}>{kicker}</Text>}
          <Text style={[styles.title, compact && styles.titleCompact]} numberOfLines={3}>
            {article.title}
          </Text>
          {!compact && article.excerpt ? (
            <Text style={styles.excerpt} numberOfLines={2}>
              {article.excerpt}
            </Text>
          ) : null}
          <Text style={styles.meta}>
            {[compact ? relation : null, meta, !compact && article.author_name ? `By ${article.author_name}` : null]
              .filter(Boolean)
              .join(" · ")}
          </Text>
          {article.reason ? <Text style={styles.reason}>Suggested: {article.reason.toLowerCase()}</Text> : null}
        </View>
      </Pressable>
    </Link>
  )
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    gap: 12,
    padding: 12,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    marginBottom: 10,
    minHeight: 48,
  },
  compact: { paddingVertical: 10 },
  pressed: { opacity: 0.8 },
  image: { width: 96, height: 72, borderRadius: 10, backgroundColor: "rgba(255,255,255,0.05)" },
  body: { flex: 1, minWidth: 0 },
  kicker: { color: theme.emerald, fontSize: 10, fontWeight: "700", textTransform: "uppercase", marginBottom: 2 },
  title: { color: theme.text, fontSize: 14, fontWeight: "600", lineHeight: 19 },
  titleCompact: { fontSize: 13, fontWeight: "500" },
  excerpt: { color: theme.textMuted, fontSize: 12, marginTop: 4, lineHeight: 16 },
  meta: { color: theme.textFaint, fontSize: 11, marginTop: 4 },
  reason: { color: theme.textFaint, fontSize: 10, marginTop: 2 },
})
