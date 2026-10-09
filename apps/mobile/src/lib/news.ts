import type { ArticleSummary, ContentNotificationKind, Trending } from "@/types/api"

// Identical in spirit to apps/web/lib/news.ts (same words, same rules) -- the
// two clients are kept in step by hand, as with notification-overrides.

const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })

/** `2 Oct 2026` (UTC, like kickoff times elsewhere in the app). */
export function formatArticleDate(iso: string | null): string {
  if (!iso) return ""
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? "" : DATE.format(date)
}

/** A plain-words reason for a trending entry, from the signals that actually
 * contributed. No numbers and no claim about quality: trending means "getting
 * attention", not "playing well". */
export function trendLabel(signals: Trending<unknown>["signals"]): string {
  if (signals.live_matches) return "Playing live now"
  if (signals.searches || signals.views || signals.match_views) return "Popular in the last 24 hours"
  if (signals.news) return "In the news"
  if (signals.follows) return "Gaining followers"
  return "Trending"
}

export function relationLabel(relation: ArticleSummary["relation"]): string | null {
  switch (relation) {
    case "match":
      return "About this match"
    case "team":
      return "Team news"
    case "competition":
      return "Competition news"
    default:
      return null
  }
}

export const CONTENT_KINDS: { kind: ContentNotificationKind; label: string; hint: string }[] = [
  { kind: "team_news", label: "Team news", hint: "Articles about a team you follow" },
  { kind: "competition_news", label: "Competition news", hint: "Articles about a competition you follow" },
  { kind: "match_reports", label: "Match reports", hint: "Reports on matches involving what you follow" },
  { kind: "transfer_news", label: "Transfer news", hint: "Transfer stories" },
  { kind: "general_news", label: "General football news", hint: "Only featured stories" },
  { kind: "comment_replies", label: "Replies to my comments", hint: "When someone replies to a comment you wrote" },
  { kind: "poll_results", label: "Poll results", hint: "The result of a poll you voted in, once it closes" },
  { kind: "editorial_updates", label: "Editorial updates", hint: "Review requests, approvals and changes requested (writers and editors)" },
  { kind: "prediction_available", label: "Match estimates", hint: "When a statistical estimate is ready for a match you follow" },
  { kind: "team_insights", label: "Matchday reminders", hint: "A heads-up on the day a team you follow plays" },
  { kind: "poll_closing", label: "Polls closing soon", hint: "A poll on a match you follow is about to close and you haven't voted" },
  { kind: "subscription_events", label: "Subscription updates", hint: "Activation, cancellation and payment problems for your Premium plan" },
]
