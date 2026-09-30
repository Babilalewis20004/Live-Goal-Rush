"use client"

import { useState } from "react"
import { useNow } from "@/hooks/use-now"
import { formatAgo, liveAnnouncement } from "@/lib/match-centre"
import type { ConnectionStatus } from "@/lib/realtime"
import type { MatchDetail } from "@/types/api"

/** Visually hidden `aria-live` region. It announces only score/status
 * *changes* (goal, half time, full time...) -- never the ticking minute or
 * unrelated updates -- so a screen-reader user following a live match isn't
 * interrupted on every poll. (Uses React's documented "adjust state while
 * rendering" pattern to compare with the previous render.) */
export function LiveAnnouncer({ match }: { match: MatchDetail }) {
  const [previous, setPrevious] = useState(match)
  const [message, setMessage] = useState("")

  if (match !== previous) {
    const next = liveAnnouncement(previous, match)
    setPrevious(match)
    if (next) setMessage(next)
  }

  return (
    <div aria-live="polite" aria-atomic="true" className="sr-only" data-testid="live-announcer">
      {message}
    </div>
  )
}

/** Shown while a live/upcoming match's socket is down: tells the user the
 * numbers on screen are the last known state and how old they are, instead of
 * silently presenting stale data as live. The REST refresh + reconnect is
 * automatic (see `RealtimeConnection`'s `onReconnect`). */
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
    <div
      role="status"
      className="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-200"
    >
      <p className="font-semibold">Connection lost — reconnecting…</p>
      <p className="text-amber-200/75">
        Showing the last known match state{ago ? `. Updated ${ago}` : ""}.
      </p>
    </div>
  )
}
