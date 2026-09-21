import { StyleSheet, Text, View } from "react-native"
import type { CompetitionOut, MatchSummary } from "@/types/api"
import { theme } from "@/theme"
import { MatchCard } from "./match-card"

export function LeagueSection({
  competition,
  matches,
}: {
  competition: CompetitionOut
  matches: MatchSummary[]
}) {
  const liveCount = matches.filter((m) => m.status === "live" || m.status === "halftime").length

  return (
    <View style={styles.section}>
      <View style={styles.header}>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={styles.title} numberOfLines={1}>
            {competition.name}
          </Text>
          {competition.country && <Text style={styles.subtitle}>{competition.country}</Text>}
        </View>
        {liveCount > 0 && (
          <View style={styles.liveBadge}>
            <Text style={styles.liveBadgeText}>{liveCount} live</Text>
          </View>
        )}
      </View>
      <View>
        {matches.map((match) => (
          <MatchCard key={match.id} match={match} />
        ))}
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  section: {
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    overflow: "hidden",
    marginBottom: 12,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.border,
  },
  title: {
    color: theme.text,
    fontSize: 14,
    fontWeight: "700",
  },
  subtitle: {
    color: theme.textFaint,
    fontSize: 11,
    marginTop: 2,
  },
  liveBadge: {
    backgroundColor: "rgba(52,211,153,0.15)",
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  liveBadgeText: {
    color: theme.emerald,
    fontSize: 11,
    fontWeight: "700",
  },
})
