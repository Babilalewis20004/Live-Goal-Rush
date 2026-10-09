import { StyleSheet, Text, View } from "react-native"

import { theme } from "@/theme"
import type { ContentBlock } from "@/types/api"

function Block({ block }: { block: ContentBlock }) {
  switch (block.type) {
    case "heading":
      return (
        <Text accessibilityRole="header" style={styles.heading}>
          {block.text}
        </Text>
      )
    case "list_item":
      return (
        <View style={styles.listItem}>
          <Text style={styles.paragraph} accessibilityElementsHidden>
            •
          </Text>
          <Text style={[styles.paragraph, { flex: 1 }]}>{block.text}</Text>
        </View>
      )
    case "quote":
      return (
        <View style={styles.quote}>
          <Text style={[styles.paragraph, { fontStyle: "italic" }]}>{block.text}</Text>
        </View>
      )
    default:
      return <Text style={styles.paragraph}>{block.text}</Text>
  }
}

/** An article body from the API's typed blocks (the server flattens the sanitized HTML,
 * so there is no HTML for the app to render or to trust). */
export function ArticleBlocks({ blocks, fallback }: { blocks: ContentBlock[]; fallback?: string }) {
  if (blocks.length === 0) return fallback ? <Text style={styles.paragraph}>{fallback}</Text> : null
  return (
    <View>
      {blocks.map((block, i) => (
        <Block key={i} block={block} />
      ))}
    </View>
  )
}

const styles = StyleSheet.create({
  heading: { color: theme.text, fontSize: 18, fontWeight: "700", marginTop: 20, marginBottom: 8 },
  paragraph: { color: "rgba(255,255,255,0.82)", fontSize: 15, lineHeight: 23, marginBottom: 14 },
  listItem: { flexDirection: "row", gap: 8, paddingLeft: 4 },
  quote: { borderLeftWidth: 2, borderLeftColor: theme.emerald, paddingLeft: 12, marginBottom: 14 },
})
