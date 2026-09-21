import { Image, StyleSheet, Text, View } from "react-native"
import { badgeStyleFor, shortCodeFor } from "@/lib/colors"

export function TeamBadge({
  name,
  shortName,
  logoUrl,
  size = 28,
}: {
  name: string
  shortName?: string | null
  logoUrl?: string | null
  size?: number
}) {
  if (logoUrl) {
    return (
      <Image
        source={{ uri: logoUrl }}
        style={{ width: size, height: size, borderRadius: size / 2 }}
        resizeMode="contain"
      />
    )
  }

  const short = shortCodeFor(name, shortName)
  const { backgroundColor, color } = badgeStyleFor(name)

  return (
    <View
      style={[
        styles.badge,
        { width: size, height: size, borderRadius: size / 2, backgroundColor },
      ]}
    >
      <Text style={[styles.text, { color, fontSize: size * 0.32 }]}>{short}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  badge: {
    alignItems: "center",
    justifyContent: "center",
  },
  text: {
    fontWeight: "800",
  },
})
