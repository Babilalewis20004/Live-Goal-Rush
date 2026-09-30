import { useEffect, useRef, type ReactNode } from "react"
import { AccessibilityInfo, Pressable, ScrollView, StyleSheet, Text, View } from "react-native"
import { useNow } from "@/hooks/use-now"
import { describeFormResult, formSequenceLabel, formatAgo, liveAnnouncement } from "@/lib/match-centre"
import type { ConnectionStatus } from "@/lib/realtime"
import { theme } from "@/theme"
import type { Capabilities, FormResult, MatchDetail, TeamFormOut } from "@/types/api"

// -- tabs ------------------------------------------------------------------------------

export interface TabDef<T extends string> {
  id: T
  label: string
}

export function TabBar<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: TabDef<T>[]
  active: T
  onChange: (id: T) => void
}) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      accessibilityRole="tablist"
      contentContainerStyle={styles.tabBar}
    >
      {tabs.map((tab) => {
        const selected = tab.id === active
        return (
          <Pressable
            key={tab.id}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            accessibilityLabel={tab.label}
            onPress={() => onChange(tab.id)}
            style={[styles.tab, selected && styles.tabSelected]}
            hitSlop={4}
          >
            <Text style={[styles.tabText, selected && styles.tabTextSelected]}>{tab.label}</Text>
          </Pressable>
        )
      })}
    </ScrollView>
  )
}

// -- honest empty states ----------------------------------------------------------------

export type FeatureKey =
  | "match_events"
  | "lineups"
  | "match_statistics"
  | "player_statistics"
  | "team_squads"
  | "player_profiles"
  | "standings"
  | "top_scorers"

const FEATURE_NAMES: Record<FeatureKey, string> = {
  match_events: "Match events",
  lineups: "Lineups",
  match_statistics: "Match statistics",
  player_statistics: "Player statistics",
  team_squads: "Squad information",
  player_profiles: "Player profiles",
  standings: "Standings",
  top_scorers: "Top scorers",
}

/** "Not available" (this data provider never supplies it) vs "not here yet"
 * -- distinguished via `GET /capabilities`, never guessed. */
export function FeatureState({
  feature,
  capabilities,
  pendingMessage,
}: {
  feature: FeatureKey
  capabilities: Capabilities | null
  pendingMessage: string
}) {
  const unsupported = capabilities !== null && capabilities[feature] === false
  return (
    <View style={styles.featureState} accessibilityRole="text">
      <Text style={styles.featureTitle}>{unsupported ? "Not available" : FEATURE_NAMES[feature]}</Text>
      <Text style={styles.featureBody}>
        {unsupported
          ? `${FEATURE_NAMES[feature]} aren't provided by the current football data provider.`
          : pendingMessage}
      </Text>
    </View>
  )
}

// -- degraded / offline -------------------------------------------------------------------

/** Shown while a live match's connection is down: the numbers on screen are
 * the last known state, and this says how old they are. Recovery is automatic:
 * REST refresh, then WebSocket reconnect (see `useMatchDetail`). */
export function StaleBanner({
  status,
  isLive,
  lastUpdatedAt,
}: {
  status: ConnectionStatus
  isLive: boolean
  lastUpdatedAt: string | null
}) {
  const now = useNow(5_000)
  if (!isLive || status === "open" || status === "connecting") return null
  const ago = formatAgo(lastUpdatedAt, now)
  return (
    <View style={styles.banner} accessibilityRole="alert">
      <Text style={styles.bannerTitle}>Connection lost</Text>
      <Text style={styles.bannerBody}>
        Showing last known match state{ago ? `\nUpdated ${ago}` : ""}
      </Text>
    </View>
  )
}

/** Announces only score/status *changes* to screen readers (not the minute
 * ticking), so following a live match isn't a stream of interruptions. */
export function LiveAnnouncer({ match }: { match: MatchDetail }) {
  const previous = useRef(match)
  useEffect(() => {
    const message = liveAnnouncement(previous.current, match)
    previous.current = match
    if (message) AccessibilityInfo.announceForAccessibility(message)
  }, [match])
  return null
}

// -- form -------------------------------------------------------------------------------------

const FORM_COLOR: Record<FormResult, { bg: string; fg: string }> = {
  W: { bg: "#10b981", fg: "#04130b" },
  D: { bg: "#a1a1aa", fg: "#0b0f0d" },
  L: { bg: "#ef4444", fg: "#ffffff" },
}

/** Recent results as W/D/L chips, oldest left, latest right. Historical only
 * -- never a prediction. */
export function FormStrip({ form, title }: { form: TeamFormOut; title: string }) {
  const ordered = [...form.results].reverse()
  return (
    <View style={{ gap: 6 }}>
      <View style={styles.formHeader}>
        <Text style={styles.formTitle} numberOfLines={1}>
          {title}
        </Text>
        <Text style={styles.formScope}>
          Last {form.limit}
          {form.scope !== "overall" ? ` · ${form.scope}` : ""}
        </Text>
      </View>
      {ordered.length === 0 ? (
        <Text style={styles.formEmpty}>No recent results stored.</Text>
      ) : (
        <View style={styles.formRow} accessible accessibilityLabel={formSequenceLabel(form.sequence)}>
          {ordered.map((r) => (
            <View
              key={r.match_id}
              style={[styles.formChip, { backgroundColor: FORM_COLOR[r.result].bg }]}
              accessibilityLabel={describeFormResult(r)}
            >
              <Text style={[styles.formChipText, { color: FORM_COLOR[r.result].fg }]}>{r.result}</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  )
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <Text style={styles.sectionTitle} accessibilityRole="header">
      {children}
    </Text>
  )
}

export function Card({ children }: { children: ReactNode }) {
  return <View style={styles.card}>{children}</View>
}

const styles = StyleSheet.create({
  tabBar: { gap: 6, paddingVertical: 4 },
  tab: {
    minHeight: 40,
    paddingHorizontal: 16,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
  },
  tabSelected: { backgroundColor: "rgba(255,255,255,0.14)", borderColor: "rgba(255,255,255,0.3)" },
  tabText: { color: theme.textMuted, fontSize: 13, fontWeight: "600" },
  tabTextSelected: { color: theme.text },
  featureState: {
    alignItems: "center",
    paddingVertical: 40,
    paddingHorizontal: 24,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    gap: 4,
  },
  featureTitle: { color: theme.textMuted, fontSize: 14, fontWeight: "700" },
  featureBody: { color: theme.textFaint, fontSize: 13, textAlign: "center" },
  banner: {
    marginTop: 10,
    padding: 12,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(251,191,36,0.4)",
    backgroundColor: "rgba(251,191,36,0.1)",
    gap: 2,
  },
  bannerTitle: { color: theme.amber, fontSize: 13, fontWeight: "700" },
  bannerBody: { color: "rgba(253,230,138,0.85)", fontSize: 12 },
  formHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", gap: 8 },
  formTitle: { color: theme.text, fontSize: 12, fontWeight: "700", flex: 1 },
  formScope: { color: theme.textFaint, fontSize: 10 },
  formEmpty: { color: theme.textFaint, fontSize: 12 },
  formRow: { flexDirection: "row", gap: 6 },
  formChip: { width: 28, height: 28, borderRadius: 6, alignItems: "center", justifyContent: "center" },
  formChipText: { fontSize: 12, fontWeight: "800" },
  sectionTitle: { color: theme.text, fontSize: 14, fontWeight: "700", marginBottom: 10 },
  card: {
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    padding: 16,
  },
})
