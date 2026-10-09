import { StyleSheet, Text, View } from "react-native"

import { LockedNote } from "@/components/analytics/premium-gate"
import { Card } from "@/components/match-centre/ui"
import { useAsync } from "@/hooks/use-async"
import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import { confidenceText, formatNumber, outcomePercentages, timeAgo } from "@/lib/analytics"
import { theme } from "@/theme"
import type { PredictionOut } from "@/types/api"

/** The model's estimate for an upcoming match. Always labelled as an estimate, always with the
 * reasons and the caveat; probabilities are numbers (the bar is decoration). */
export function PredictionView({ prediction, homeName, awayName, signedIn }: { prediction: PredictionOut; homeName: string; awayName: string; signedIn: boolean }) {
  if (prediction.status !== "available") {
    return (
      <Card>
        <Text style={styles.title} accessibilityRole="header">Model estimate</Text>
        <Text style={styles.muted}>{prediction.reason ?? "No estimate is available for this match."}</Text>
      </Card>
    )
  }
  const outcomes = outcomePercentages(prediction, { home: homeName, away: awayName })
  const generated = timeAgo(prediction.generated_at)
  const spoken = outcomes ? outcomes.map((o) => `${o.label} ${o.percent} percent`).join(", ") : ""
  return (
    <Card>
      <View style={styles.header}>
        <Text style={styles.title} accessibilityRole="header">Model estimate</Text>
        <Text style={styles.tag}>Statistical prediction</Text>
      </View>
      {outcomes && (
        <>
          <View style={styles.bar} accessible accessibilityLabel={spoken}>
            <View style={{ flex: Math.max(outcomes[0].percent, 1), backgroundColor: theme.emerald }} />
            <View style={{ flex: Math.max(outcomes[1].percent, 1), backgroundColor: "rgba(255,255,255,0.4)" }} />
            <View style={{ flex: Math.max(outcomes[2].percent, 1), backgroundColor: "#38bdf8" }} />
          </View>
          <View style={styles.row}>
            {outcomes.map((o) => (
              <View key={o.key} style={styles.cell} accessible accessibilityLabel={`${o.label} ${o.percent} percent`}>
                <Text style={styles.cellLabel} numberOfLines={1}>{o.label}</Text>
                <Text style={styles.cellValue}>{o.percent}%</Text>
              </View>
            ))}
          </View>
        </>
      )}
      <Text style={styles.muted}>
        Expected total goals: {formatNumber(prediction.expected_total_goals)}
        {prediction.expected_home_goals !== null && prediction.expected_away_goals !== null
          ? ` (${homeName} ${formatNumber(prediction.expected_home_goals)}, ${awayName} ${formatNumber(prediction.expected_away_goals)})`
          : ""}
      </Text>
      {confidenceText(prediction.confidence) && <Text style={styles.muted}>{confidenceText(prediction.confidence)}.</Text>}
      {prediction.influences.length > 0 && (
        <View style={{ marginTop: 8, gap: 2 }}>
          <Text style={styles.sub}>Prediction influenced by</Text>
          {prediction.influences.map((i) => (
            <Text key={i} style={styles.muted}>• {i}</Text>
          ))}
        </View>
      )}
      <LockedNote locked={prediction.locked} signedIn={signedIn} />
      <Text style={styles.fine}>
        {prediction.disclaimer} Based on available historical data
        {prediction.model_version ? ` · model ${prediction.model_version}` : ""}
        {generated ? ` · generated ${generated}` : ""}.
      </Text>
    </Card>
  )
}

export function PredictionCard({ matchId, homeName, awayName, nudge = 0 }: { matchId: number; homeName: string; awayName: string; nudge?: number }) {
  const { user } = useAuth()
  const { data, error, loading } = useAsync(() => api.getMatchPrediction(matchId), `prediction:${matchId}:${user?.id ?? "anon"}`, nudge)
  if (loading && !data) return <Card><Text style={styles.muted}>Loading estimate…</Text></Card>
  if (error || !data) {
    return (
      <Card>
        <Text style={styles.title} accessibilityRole="header">Model estimate</Text>
        <Text style={styles.muted}>The estimate isn&apos;t available right now.</Text>
      </Card>
    )
  }
  return <PredictionView prediction={data} homeName={homeName} awayName={awayName} signedIn={!!user} />
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" },
  title: { color: theme.text, fontSize: 14, fontWeight: "700" },
  tag: { color: theme.textMuted, fontSize: 10, textTransform: "uppercase" },
  bar: { flexDirection: "row", height: 8, borderRadius: 4, overflow: "hidden", marginTop: 12 },
  row: { flexDirection: "row", marginTop: 10, marginBottom: 8 },
  cell: { flex: 1, alignItems: "center" },
  cellLabel: { color: theme.textMuted, fontSize: 11 },
  cellValue: { color: theme.text, fontSize: 20, fontWeight: "700" },
  muted: { color: theme.textMuted, fontSize: 12, lineHeight: 18, marginTop: 2 },
  sub: { color: theme.textMuted, fontSize: 11, fontWeight: "700", textTransform: "uppercase" },
  fine: { color: theme.textMuted, fontSize: 10, lineHeight: 15, marginTop: 10 },
})
