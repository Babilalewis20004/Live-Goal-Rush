import { Link, useLocalSearchParams } from "expo-router"
import { useCallback, useEffect, useState } from "react"
import { ScrollView, StyleSheet, Text, View } from "react-native"

import { ReportProfile } from "@/components/community/report-profile"
import { ErrorState } from "@/components/error-state"
import { LoadingState } from "@/components/loading-state"
import { ApiError, api } from "@/lib/api"
import { relativeTime } from "@/lib/community"
import { theme } from "@/theme"
import type { ProfileOut } from "@/types/api"

/** A public profile. Private and missing profiles look identical (the API answers 404 for both). */
export default function PublicProfileScreen() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const [profile, setProfile] = useState<ProfileOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setProfile(await api.getProfile(Number(id)))
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "This profile isn't available." : "Unable to load this profile.")
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const handle = setTimeout(load, 0)
    return () => clearTimeout(handle)
  }, [load])

  if (loading) return <View style={styles.screen}><LoadingState label="Loading profile…" /></View>
  if (error || !profile) return <View style={styles.screen}><ErrorState message={error ?? "Unable to load this profile."} onRetry={load} /></View>

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.card}>
        <Text accessibilityRole="header" style={styles.name}>
          {profile.display_name}
        </Text>
        <Text style={styles.meta}>Joined {new Date(profile.joined).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" })}</Text>
        {profile.bio ? <Text style={styles.bio}>{profile.bio}</Text> : null}
        {profile.badges.length > 0 ? (
          <View style={styles.badges}>
            {profile.badges.map((b) => (
              <View key={b.key} style={styles.badge} accessible accessibilityLabel={`${b.label}: ${b.description}`}>
                <Text style={styles.badgeText}>{b.label}</Text>
              </View>
            ))}
          </View>
        ) : null}
        <View style={styles.stats}>
          {[
            ["Comments", profile.stats.comments],
            ["Poll votes", profile.stats.poll_votes],
            ["Teams followed", profile.stats.followed_teams],
          ].map(([label, value]) => (
            <View key={String(label)} style={styles.stat} accessible accessibilityLabel={`${label}: ${value}`}>
              <Text style={styles.meta}>{label}</Text>
              <Text style={styles.statValue}>{value}</Text>
            </View>
          ))}
        </View>
        <ReportProfile userId={profile.id} />
      </View>

      {profile.favourite_teams.length + profile.favourite_competitions.length > 0 ? (
        <View style={styles.card}>
          <Text accessibilityRole="header" style={styles.section}>
            Follows
          </Text>
          <View style={styles.badges}>
            {profile.favourite_teams.map((t) => (
              <Link key={`t${t.id}`} href={{ pathname: "/team/[id]", params: { id: String(t.id) } }} style={styles.chip}>
                {t.name}
              </Link>
            ))}
            {profile.favourite_competitions.map((c) => (
              <Link key={`c${c.id}`} href={{ pathname: "/competition/[id]", params: { id: String(c.id) } }} style={styles.chip}>
                {c.name}
              </Link>
            ))}
          </View>
        </View>
      ) : null}

      {profile.activity.length > 0 ? (
        <View style={styles.card}>
          <Text accessibilityRole="header" style={styles.section}>
            Recent comments
          </Text>
          {profile.activity.map((a, i) => (
            <View key={i} style={{ gap: 2 }}>
              <Text style={styles.body}>{a.text}</Text>
              <Text style={styles.meta}>
                on{" "}
                {a.target_type === "article" && a.target_slug ? (
                  <Link href={{ pathname: "/article/[slug]", params: { slug: a.target_slug } }} style={styles.link}>
                    {a.target_label}
                  </Link>
                ) : (
                  <Link href={{ pathname: "/match/[id]", params: { id: String(a.target_id) } }} style={styles.link}>
                    {a.target_label}
                  </Link>
                )}{" "}
                · {relativeTime(a.created_at)}
              </Text>
            </View>
          ))}
        </View>
      ) : null}
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.background },
  content: { padding: 16, gap: 12, paddingBottom: 48 },
  card: { borderRadius: 16, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, backgroundColor: theme.card, padding: 16, gap: 10 },
  name: { color: theme.text, fontSize: 20, fontWeight: "700" },
  meta: { color: theme.textFaint, fontSize: 12 },
  bio: { color: theme.textMuted, fontSize: 14, lineHeight: 20 },
  body: { color: "rgba(255,255,255,0.85)", fontSize: 14, lineHeight: 20 },
  badges: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  badge: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, backgroundColor: "rgba(255,255,255,0.05)" },
  badgeText: { color: theme.textMuted, fontSize: 12 },
  stats: { flexDirection: "row", gap: 8 },
  stat: { flex: 1, alignItems: "center", paddingVertical: 8, borderRadius: 10, backgroundColor: "rgba(255,255,255,0.04)" },
  statValue: { color: theme.text, fontSize: 16, fontWeight: "700" },
  section: { color: theme.text, fontSize: 14, fontWeight: "700" },
  chip: { color: theme.textMuted, fontSize: 12, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, overflow: "hidden" },
  link: { color: theme.emerald },
})
