import { ActivityIndicator, StyleSheet, Text, View } from "react-native"
import { theme } from "@/theme"

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <View style={styles.container}>
      <ActivityIndicator color={theme.emerald} />
      <Text style={styles.label}>{label}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 48,
    gap: 12,
  },
  label: {
    color: theme.textFaint,
    fontSize: 13,
  },
})
