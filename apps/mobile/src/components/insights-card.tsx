import { StyleSheet, Text, View } from "react-native"

import { theme } from "@/theme"
import type { Insight } from "@/types/api"

/** Form summaries, streaks and head-to-head as sentences: arithmetic over stored
 * results, never a prediction. Renders nothing when there is nothing honest to say. */
export function InsightsBlock({ title, insights }: { title: string; insights: Insight[] }) {
  if (insights.length === 0) return null
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.title}>{title}</Text>
      {insights.map((i) => (
        <View key={i.key} style={styles.row} accessible accessibilityLabel={i.text}>
          <View style={styles.dot} />
          <Text style={styles.text}>{i.text}</Text>
        </View>
      ))}
    </View>
  )
}

const styles = StyleSheet.create({
  title: { color: theme.textFaint, fontSize: 11, fontWeight: "700", textTransform: "uppercase" },
  row: { flexDirection: "row", gap: 8, alignItems: "flex-start" },
  dot: { width: 4, height: 4, borderRadius: 2, backgroundColor: theme.emerald, marginTop: 8 },
  text: { color: "rgba(255,255,255,0.82)", fontSize: 13, lineHeight: 19, flex: 1 },
})
