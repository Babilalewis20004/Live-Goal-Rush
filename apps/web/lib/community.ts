import type { PollOut, ReactionKind, ReactionSummary } from "@/types/api"

/** Mirrors the API's limits so most mistakes are caught before a round trip. The
 * server is still the authority (it also checks account age for links, rate
 * limits and duplicates). */
export const COMMENT_MAX_LENGTH = 2000
export const COMMENT_MAX_LINKS = 2

const LINK = /(https?:\/\/|www\.)/gi

export function countLinks(text: string): number {
  return (text.match(LINK) ?? []).length
}

export function validateComment(text: string): string | null {
  const trimmed = text.trim()
  if (!trimmed) return "Write something first."
  if (trimmed.length > COMMENT_MAX_LENGTH) return `Comments are limited to ${COMMENT_MAX_LENGTH} characters.`
  if (countLinks(trimmed) > COMMENT_MAX_LINKS) return `Please include at most ${COMMENT_MAX_LINKS} links.`
  return null
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return ""
  const seconds = Math.max(0, Math.round((now.getTime() - then.getTime()) / 1000))
  if (seconds < 45) return "just now"
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days} d ago`
  return then.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
}

export const REACTIONS: { kind: ReactionKind; emoji: string; label: string }[] = [
  { kind: "thumbs_up", emoji: "👍", label: "Thumbs up" },
  { kind: "fire", emoji: "🔥", label: "Fire" },
  { kind: "wow", emoji: "😮", label: "Wow" },
  { kind: "goal", emoji: "⚽", label: "Goal" },
  { kind: "heart", emoji: "❤️", label: "Love" },
  { kind: "laugh", emoji: "😂", label: "Funny" },
  { kind: "clap", emoji: "👏", label: "Applause" },
]

/** The summary after the viewer picks `kind` (or taps their current reaction
 * again to remove it), computed locally so the button responds instantly; the
 * server's answer then replaces it. */
export function applyReaction(summary: ReactionSummary, kind: ReactionKind): ReactionSummary {
  const counts = { ...summary.counts }
  if (summary.mine) counts[summary.mine] = Math.max(0, counts[summary.mine] - 1)
  const mine = summary.mine === kind ? null : kind
  if (mine) counts[mine] = (counts[mine] ?? 0) + 1
  return { counts, total: Object.values(counts).reduce((a, b) => a + b, 0), mine }
}

export const EMPTY_REACTIONS: ReactionSummary = {
  counts: { thumbs_up: 0, fire: 0, wow: 0, goal: 0, heart: 0, laugh: 0, clap: 0 },
  total: 0,
  mine: null,
}

/** Closing time in words: "Closes in 2 h", "Closed", or "" when open-ended. */
export function pollClosing(poll: PollOut, now: Date = new Date()): string {
  if (poll.status === "closed") return "Closed"
  if (!poll.closes_at) return ""
  const ms = new Date(poll.closes_at).getTime() - now.getTime()
  if (ms <= 0) return "Closing now"
  const minutes = Math.round(ms / 60000)
  if (minutes < 60) return `Closes in ${minutes} min`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `Closes in ${hours} h`
  return `Closes in ${Math.round(hours / 24)} d`
}

/** The option(s) leading a poll, for a text description that doesn't rely on bar colour. */
export function leadingOption(poll: PollOut): string | null {
  if (poll.total_votes === 0) return null
  const top = Math.max(...poll.options.map((o) => o.votes))
  const leaders = poll.options.filter((o) => o.votes === top)
  return leaders.length === 1 ? leaders[0].label : null
}
