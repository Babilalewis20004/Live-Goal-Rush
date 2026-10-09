import { Image } from "expo-image"
import { StyleSheet, Text, View } from "react-native"
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
      // expo-image keeps crests in memory and on disk: a livescore list shows the same few dozen crests over and
      // over, and the built-in Image re-decodes them (and on Android may refetch them) as rows scroll in and out.
      <Image
        source={{ uri: logoUrl }}
        style={{ width: size, height: size, borderRadius: size / 2 }}
        contentFit="contain"
        cachePolicy="memory-disk"
        recyclingKey={logoUrl}
        accessibilityLabel={`${name} crest`}
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
