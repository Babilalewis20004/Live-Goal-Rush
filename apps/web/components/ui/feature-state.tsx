import type { Capabilities } from "@/types/api"

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

/** The two very different reasons a section can be empty. `unsupported`: the
 * active data provider never supplies this (see `GET /capabilities`).
 * Anything else: it would be supplied, it just isn't there (yet). Saying so
 * honestly beats an empty box that looks like a bug. */
export function isUnsupported(capabilities: Capabilities | null, feature: FeatureKey): boolean {
  return capabilities !== null && capabilities[feature] === false
}

export function FeatureState({
  feature,
  capabilities,
  pendingMessage,
}: {
  feature: FeatureKey
  capabilities: Capabilities | null
  /** Shown when the feature is supported but there's no data yet. */
  pendingMessage: string
}) {
  const unsupported = isUnsupported(capabilities, feature)
  return (
    <div
      role="status"
      className="rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-10 text-center text-sm text-white/45"
    >
      <p className="font-medium text-white/60">{unsupported ? "Not available" : FEATURE_NAMES[feature]}</p>
      <p className="mt-1">
        {unsupported
          ? `${FEATURE_NAMES[feature]} aren't provided by the current football data provider.`
          : pendingMessage}
      </p>
    </div>
  )
}
