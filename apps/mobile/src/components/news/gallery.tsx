import { Image } from "expo-image"
import { useState } from "react"
import { Linking, Pressable, StyleSheet, Text, View } from "react-native"

import { theme } from "@/theme"
import type { GalleryImage } from "@/types/api"

/** An article's photo gallery. Tapping a picture opens the full-size image; each has
 * alt text (its caption, else the editor's description, else the file name). */
export function Gallery({ images }: { images: GalleryImage[] }) {
  const [failed, setFailed] = useState<Set<number>>(new Set())
  if (images.length === 0) return null
  return (
    <View style={{ marginTop: 24 }}>
      <Text accessibilityRole="header" style={styles.title}>
        Gallery
      </Text>
      <View style={styles.grid}>
        {images.map((image) => (
          <View key={image.media_id} style={styles.cell}>
            <Pressable
              accessibilityRole="imagebutton"
              accessibilityLabel={`${image.alt}. Opens the full-size image`}
              onPress={() => void Linking.openURL(image.url)}
              style={styles.thumb}
            >
              {failed.has(image.media_id) ? (
                <Text style={styles.fallback}>Image unavailable</Text>
              ) : (
                <Image
                  source={{ uri: image.thumb_url }}
                  accessibilityLabel={image.alt}
                  style={StyleSheet.absoluteFill}
                  contentFit="cover"
                  onError={() => setFailed((s) => new Set(s).add(image.media_id))}
                />
              )}
            </Pressable>
            {image.caption ? <Text style={styles.caption}>{image.caption}</Text> : null}
          </View>
        ))}
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  title: { color: theme.textFaint, fontSize: 11, fontWeight: "700", textTransform: "uppercase", marginBottom: 8 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  cell: { width: "48.5%" },
  thumb: { aspectRatio: 4 / 3, borderRadius: 10, overflow: "hidden", backgroundColor: "rgba(255,255,255,0.05)", alignItems: "center", justifyContent: "center" },
  caption: { color: theme.textFaint, fontSize: 11, marginTop: 4 },
  fallback: { color: theme.textFaint, fontSize: 11 },
})
