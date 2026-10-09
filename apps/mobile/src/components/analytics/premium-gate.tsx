import { Link } from "expo-router"
import { Pressable, StyleSheet, Text, View } from "react-native"

import { theme } from "@/theme"

/** Shown where Premium detail is withheld. The free view next to it stays useful; this only
 * explains what the upgrade adds. Withholding is done by the server -- this is just the explanation. */
export function PremiumGate({ title, items, signedIn }: { title: string; items?: string[]; signedIn: boolean }) {
  return (
    <View style={styles.box} accessible accessibilityLabel={`${title} is a Premium feature`}>
      <Text style={styles.title}>🔒 {title}</Text>
      {items?.map((i) => (
        <Text key={i} style={styles.item}>
          • {i}
        </Text>
      ))}
      <Text style={styles.body}>Livescores, the match centre, news and community stay free.</Text>
      <UpgradeLink signedIn={signedIn} />
    </View>
  )
}

export function UpgradeLink({ signedIn }: { signedIn: boolean }) {
  return (
    <Link href={signedIn ? "/premium" : "/login"} asChild>
      <Pressable accessibilityRole="link" accessibilityLabel={signedIn ? "See Premium" : "Sign in to see Premium"} hitSlop={8} style={styles.link}>
        <Text style={styles.linkText}>{signedIn ? "See Premium →" : "Sign in to see Premium →"}</Text>
      </Pressable>
    </Link>
  )
}

/** A one-line note under a free view listing what Premium would add. */
export function LockedNote({ locked, signedIn }: { locked: string[]; signedIn: boolean }) {
  if (locked.length === 0) return null
  return (
    <View style={{ marginTop: 10 }}>
      <Text style={styles.note}>🔒 More detail ({locked.join(", ").replaceAll("_", " ")}) is part of Premium.</Text>
      <UpgradeLink signedIn={signedIn} />
    </View>
  )
}

const styles = StyleSheet.create({
  box: { borderWidth: 1, borderColor: "rgba(52,211,153,0.25)", backgroundColor: "rgba(52,211,153,0.05)", borderRadius: 14, padding: 14, gap: 4 },
  title: { color: theme.text, fontSize: 14, fontWeight: "700" },
  item: { color: theme.textMuted, fontSize: 12 },
  body: { color: theme.textMuted, fontSize: 12, marginTop: 6 },
  link: { minHeight: 36, justifyContent: "center", alignSelf: "flex-start" },
  linkText: { color: theme.emerald, fontSize: 13, fontWeight: "600" },
  note: { color: theme.textMuted, fontSize: 11 },
})
