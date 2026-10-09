import { StyleSheet, Text, View } from "react-native"

import { theme } from "@/theme"

/** Shown whenever the scores on screen may not match reality (offline, reconnecting, or a saved copy). */
export function StaleBanner({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <View accessibilityRole="alert" accessibilityLiveRegion="polite" style={styles.banner}>
      <View style={styles.dot} />
      <Text style={styles.text}>{message}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.amber,
    backgroundColor: "rgba(245,158,11,0.08)",
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: theme.amber },
  text: { flex: 1, color: theme.amber, fontSize: 12, lineHeight: 16 },
})
