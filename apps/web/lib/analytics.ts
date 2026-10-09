import type { ComparisonRow, EntitlementsOut, PlanOut, PredictionOut, Stat } from "@/types/api"

/** Presentation helpers for analytics, predictions and Premium. Pure functions
 * (no network, no clock) so they can be unit tested; kept identical by hand in
 * apps/mobile/src/lib/analytics.ts. The server decides what anyone may see --
 * nothing here grants access. */

export const NOT_AVAILABLE = "—"

export const ENTITLEMENT = {
  advancedAnalytics: "advanced_analytics",
  extendedHistory: "extended_history",
  advancedComparison: "advanced_comparison",
  predictionDetails: "prediction_details",
  playerAnalytics: "player_analytics",
  adFree: "ad_free",
} as const

export function hasEntitlement(entitlements: readonly string[] | undefined, key: string): boolean {
  return !!entitlements && entitlements.includes(key)
}

/** `12.5` -> "12.5", `12` -> "12", missing -> "—". Never shows a missing value as 0. */
export function formatStat(stat: Stat | undefined | null, opts: { digits?: number; suffix?: string } = {}): string {
  if (!stat || stat.value === null) return NOT_AVAILABLE
  const digits = opts.digits ?? 1
  const text = Number.isInteger(stat.value) ? String(stat.value) : stat.value.toFixed(digits).replace(/\.?0+$/, "")
  return `${text}${opts.suffix ?? ""}`
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return NOT_AVAILABLE
  return Number.isInteger(value) ? String(value) : value.toFixed(digits).replace(/\.?0+$/, "")
}

/** "3 of 10 matches" when only some matches had the statistic, otherwise null. */
export function coverage(stat: Stat | undefined | null, matches: number): string | null {
  if (!stat || stat.value === null || matches <= 0 || stat.sample >= matches) return null
  return `${stat.sample} of ${matches} matches`
}

export interface Outcome {
  key: "home" | "draw" | "away"
  label: string
  percent: number
}

/** Whole-number percentages that always sum to 100 (largest remainder), so the
 * three figures on screen never add up to 99 or 101. */
export function outcomePercentages(p: Pick<PredictionOut, "home_win" | "draw" | "away_win">, names: { home: string; away: string }): Outcome[] | null {
  if (p.home_win === null || p.draw === null || p.away_win === null) return null
  const raw = [
    { key: "home" as const, label: names.home, value: p.home_win * 100 },
    { key: "draw" as const, label: "Draw", value: p.draw * 100 },
    { key: "away" as const, label: names.away, value: p.away_win * 100 },
  ]
  const floors = raw.map((r) => Math.floor(r.value))
  let remaining = 100 - floors.reduce((a, b) => a + b, 0)
  const order = raw
    .map((r, i) => ({ i, frac: r.value - floors[i] }))
    .sort((a, b) => b.frac - a.frac || a.i - b.i)
  for (const { i } of order) {
    if (remaining <= 0) break
    floors[i] += 1
    remaining -= 1
  }
  return raw.map((r, i) => ({ key: r.key, label: r.label, percent: floors[i] }))
}

export const CONFIDENCE_TEXT: Record<string, string> = {
  low: "Low confidence: little history to go on",
  medium: "Medium confidence",
  high: "Higher confidence: plenty of recent matches",
}

export function confidenceText(confidence: PredictionOut["confidence"]): string | null {
  return confidence ? CONFIDENCE_TEXT[confidence] : null
}

/** Bar shares for a comparison row, or null when either side has no data (so no bar is drawn
 * rather than a misleading one). */
export function comparisonShares(row: Pick<ComparisonRow, "home" | "away">): { home: number; away: number } | null {
  if (row.home === null || row.away === null) return null
  const total = row.home + row.away
  if (total <= 0) return { home: 50, away: 50 }
  const home = Math.round((row.home / total) * 100)
  return { home, away: 100 - home }
}

/** Which side is ahead on a row, taking "higher is better" into account (null = neutral or no data). */
export function leader(row: ComparisonRow): "home" | "away" | "level" | null {
  if (row.home === null || row.away === null || row.higher_is_better === null) return null
  if (row.home === row.away) return "level"
  const homeHigher = row.home > row.away
  return homeHigher === row.higher_is_better ? "home" : "away"
}

export function rowSummary(row: ComparisonRow, names: { home: string; away: string }): string {
  const side = leader(row)
  const values = `${names.home} ${formatNumber(row.home)}, ${names.away} ${formatNumber(row.away)}`
  const lead = side === "home" ? `${names.home} ahead` : side === "away" ? `${names.away} ahead` : side === "level" ? "level" : ""
  return [row.label + ":", values + (lead ? `; ${lead}` : "")].join(" ")
}

export function formatPrice(plan: Pick<PlanOut, "price_minor" | "currency" | "interval">, locale = "en-GB"): string {
  const amount = new Intl.NumberFormat(locale, { style: "currency", currency: plan.currency }).format(plan.price_minor / 100)
  return `${amount} / ${plan.interval}`
}

export function isPremium(entitlements: EntitlementsOut | null | undefined): boolean {
  return !!entitlements && entitlements.premium
}

export function subscriptionStatusText(status: string, cancelAtPeriodEnd: boolean, periodEnd: string | null): string {
  const until = periodEnd ? new Date(periodEnd).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : null
  switch (status) {
    case "active":
      return until ? `Premium is active. Renews on ${until}.` : "Premium is active."
    case "cancelled":
      return until ? `Cancelled. You keep Premium until ${until}.` : "Cancelled."
    case "past_due":
      return "We couldn't take your last payment. Please update your payment method to keep Premium."
    case "expired":
      return "Your Premium plan has ended. Free features stay available."
    default:
      return cancelAtPeriodEnd ? "Cancelling at the end of the period." : "You're on the free plan."
  }
}

export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string | null {
  if (!iso) return null
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return null
  const minutes = Math.max(0, Math.round((now.getTime() - then.getTime()) / 60000))
  if (minutes < 2) return "just now"
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}
