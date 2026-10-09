import { useState } from "react"
import { Pressable, StyleSheet, Text, View } from "react-native"

import { AdSlot } from "@/components/analytics/ad-slot"
import { ComparisonPanel } from "@/components/analytics/comparison-panel"
import { PremiumGate } from "@/components/analytics/premium-gate"
import { PredictionCard } from "@/components/analytics/prediction-card"
import { Card, SectionTitle } from "@/components/match-centre/ui"
import { isPaymentRequired, useAsync } from "@/hooks/use-async"
import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import { formatNumber } from "@/lib/analytics"
import { theme } from "@/theme"
import type { MatchDetail } from "@/types/api"

function KeyInsights({ matchId, nudge }: { matchId: number; nudge: number }) {
  const { data } = useAsync(() => api.getMatchInsightRecords(matchId), `insight-records:${matchId}`, nudge)
  if (!data || data.length === 0) return null
  const live = data.filter((i) => i.insight_type.startsWith("live:"))
  const rest = data.filter((i) => !i.insight_type.startsWith("live:") && !i.insight_type.endsWith("form_summary") && !i.insight_type.endsWith("goal_average"))
  const items = [...live, ...rest].slice(0, 8)
  if (items.length === 0) return null
  return (
    <Card>
      <SectionTitle>Key insights</SectionTitle>
      <View style={{ gap: 6 }}>
        {items.map((i) => (
          <View key={i.insight_type} style={styles.bullet} accessible accessibilityLabel={`${i.insight_type.startsWith("live:") ? "Live. " : ""}${i.text}`}>
            <View style={styles.dot} />
            <Text style={styles.text}>
              {i.insight_type.startsWith("live:") ? "LIVE · " : ""}
              {i.text}
            </Text>
          </View>
        ))}
      </View>
      <Text style={styles.fine}>Each insight is calculated from stored results or live statistics. Historical information, not a prediction.</Text>
    </Card>
  )
}

const WINDOWS = [
  { id: "last5", label: "Last 5" },
  { id: "last10", label: "Last 10 🔒" },
  { id: "all", label: "All meetings 🔒" },
] as const

function ExtendedHistory({ match }: { match: MatchDetail }) {
  const { user } = useAuth()
  const [window, setWindow] = useState<(typeof WINDOWS)[number]["id"]>("last5")
  const { data, error } = useAsync(
    () => (window === "last5" ? api.getMatchHeadToHead(match.id) : api.getExtendedHeadToHead(match.id, window)),
    `h2h:${match.id}:${window}:${user?.id ?? "anon"}`,
  )
  return (
    <Card>
      <SectionTitle>Head-to-head history</SectionTitle>
      <View style={styles.chips}>
        {WINDOWS.map((w) => (
          <Pressable key={w.id} accessibilityRole="button" accessibilityState={{ selected: window === w.id }} accessibilityLabel={w.label} onPress={() => setWindow(w.id)} hitSlop={4}
            style={[styles.chip, window === w.id && styles.chipOn]}>
            <Text style={[styles.chipText, window === w.id && { color: theme.text }]}>{w.label}</Text>
          </Pressable>
        ))}
      </View>
      {isPaymentRequired(error) ? (
        <PremiumGate title="Longer head-to-head history" items={["The last 10 meetings", "Every stored meeting"]} signedIn={!!user} />
      ) : data ? (
        <View style={{ gap: 4 }}>
          <Text style={styles.text}>
            {data.total_meetings ?? data.meetings.length} meetings: {match.home_team.name} {data.home_team_wins} wins, {data.draws} draws, {match.away_team.name} {data.away_team_wins} wins.
          </Text>
          {data.average_goals !== null && data.average_goals !== undefined && (
            <Text style={styles.muted}>{formatNumber(data.average_goals)} goals per meeting ({data.home_team_goals}–{data.away_team_goals} overall).</Text>
          )}
          {data.recent_form ? <Text style={styles.muted}>{match.home_team.name} in these meetings, oldest to newest: {data.recent_form}</Text> : null}
          {data.limitation ? <Text style={styles.warn}>{data.limitation}</Text> : null}
        </View>
      ) : (
        <Text style={styles.muted}>{error ? "Head-to-head isn't available right now." : "Loading…"}</Text>
      )}
    </Card>
  )
}

/** The match centre's Analysis tab: model estimate, comparison, key insights, longer history.
 * Refreshes when the server nudges over the existing match WebSocket. */
export function AnalysisTab({ match, nudges }: { match: MatchDetail; nudges: Record<string, number> }) {
  return (
    <View style={{ gap: 12 }}>
      <PredictionCard matchId={match.id} homeName={match.home_team.name} awayName={match.away_team.name} nudge={nudges["prediction.updated"] ?? 0} />
      <ComparisonPanel matchId={match.id} />
      <KeyInsights matchId={match.id} nudge={nudges["match.insight.updated"] ?? 0} />
      <ExtendedHistory match={match} />
      <AdSlot placement="match_centre" live={match.status === "live" || match.status === "halftime"} />
    </View>
  )
}

const styles = StyleSheet.create({
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginVertical: 8 },
  chip: { minHeight: 36, paddingHorizontal: 12, borderRadius: 999, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.border, justifyContent: "center" },
  chipOn: { borderColor: "rgba(52,211,153,0.6)", backgroundColor: "rgba(52,211,153,0.15)" },
  chipText: { color: theme.textMuted, fontSize: 12 },
  bullet: { flexDirection: "row", gap: 8, alignItems: "flex-start" },
  dot: { width: 4, height: 4, borderRadius: 2, backgroundColor: theme.emerald, marginTop: 8 },
  text: { color: "rgba(255,255,255,0.82)", fontSize: 13, lineHeight: 19, flex: 1 },
  muted: { color: theme.textMuted, fontSize: 12 },
  warn: { color: "rgba(253,230,138,0.75)", fontSize: 11 },
  fine: { color: theme.textMuted, fontSize: 10, marginTop: 8 },
})
