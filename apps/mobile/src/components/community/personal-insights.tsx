import { router } from "expo-router"
import { Pressable, StyleSheet, Text, View } from "react-native"

import { useAsync } from "@/hooks/use-async"
import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import { theme } from "@/theme"

/** "Your followed team has a match today" and similar. Each line is a plain statement of a stored
 * fixture or result for something the viewer follows; nothing appears for people who follow nothing. */
export function PersonalInsights() {
  const { user } = useAuth()
  const { data } = useAsync(() => api.getMyInsights(), `my-insights:${user?.id ?? "anon"}`, 0, !!user)
  if (!user || !data || data.length === 0) return null
  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.title}>For you</Text>
      {data.map((i) => (
        <Pressable
          key={`${i.key}-${i.entity_id}`}
          accessibilityRole="link"
          accessibilityLabel={i.text}
          hitSlop={4}
          style={styles.row}
          onPress={() =>
            i.entity_type === "match"
              ? router.push({ pathname: "/match/[id]", params: { id: String(i.entity_id) } })
              : router.push({ pathname: "/competition/[id]", params: { id: String(i.entity_id) } })
          }
        >
          <View style={styles.dot} />
          <Text style={styles.text}>{i.text}</Text>
        </Pressable>
      ))}
    </View>
  )
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderColor: theme.border, backgroundColor: theme.card, borderRadius: 16, padding: 14, gap: 6, marginHorizontal: 16, marginBottom: 12 },
  title: { color: theme.text, fontSize: 14, fontWeight: "700" },
  row: { flexDirection: "row", gap: 8, alignItems: "flex-start", minHeight: 32 },
  dot: { width: 4, height: 4, borderRadius: 2, backgroundColor: theme.emerald, marginTop: 9 },
  text: { color: "rgba(255,255,255,0.82)", fontSize: 13, lineHeight: 19, flex: 1 },
})
