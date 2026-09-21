"use client"

import { ChevronDown, Star } from "lucide-react"
import { useState } from "react"
import type { Match } from "@/lib/matches"
import { MatchDetail } from "./match-detail"
import { TeamBadge } from "./team-badge"

function StatusPill({ match }: { match: Match }) {
  if (match.status === "live") {
    return (
      <div className="flex flex-col items-center gap-1">
        <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-400">
          <span className="ls-live-dot h-1.5 w-1.5 rounded-full bg-emerald-400" />
          {match.minute}&apos;
        </span>
      </div>
    )
  }
  if (match.status === "halftime") {
    return (
      <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-400">HT</span>
    )
  }
  if (match.status === "finished") {
    return <span className="text-[11px] font-semibold text-white/40">FT</span>
  }
  return <span className="text-[11px] font-semibold text-white/50">{match.kickoff}</span>
}

function Score({ value, live, dim }: { value: number; live?: boolean; dim?: boolean }) {
  return (
    <span
      className={[
        "w-6 text-center text-base font-bold tabular-nums",
        live ? "text-emerald-400" : dim ? "text-white/40" : "text-white",
      ].join(" ")}
    >
      {value}
    </span>
  )
}

export function MatchCard({ match }: { match: Match }) {
  const [fav, setFav] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const isLive = match.status === "live"
  const upcoming = match.status === "upcoming"
  const homeWin = match.homeScore > match.awayScore
  const awayWin = match.awayScore > match.homeScore

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-label={`${match.home.name} vs ${match.away.name}, ${expanded ? "hide" : "show"} details`}
        onClick={() => setExpanded((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault()
            setExpanded((v) => !v)
          }
        }}
        className={[
          "group relative flex cursor-pointer items-center gap-3 overflow-hidden px-4 py-3 transition-colors",
          "hover:bg-white/[0.04]",
        ].join(" ")}
      >
        {/* live left accent + sweep */}
        {isLive && (
          <>
            <span className="absolute left-0 top-0 h-full w-0.5 bg-emerald-400" />
            <span className="ls-sweep pointer-events-none absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-transparent via-emerald-400/[0.07] to-transparent" />
          </>
        )}

        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            setFav((v) => !v)
          }}
          aria-pressed={fav}
          aria-label={fav ? "Remove from favourites" : "Add to favourites"}
          className="shrink-0 text-white/25 transition-colors hover:text-amber-300"
        >
          <Star className="h-4 w-4" fill={fav ? "currentColor" : "none"} style={{ color: fav ? "#fbbf24" : undefined }} />
        </button>

        <div className="w-12 shrink-0 text-center">
          <StatusPill match={match} />
        </div>

        <div className="min-w-0 flex-1">
          {/* home row */}
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2.5">
              <TeamBadge team={match.home} />
              <span
                className={[
                  "truncate text-sm",
                  upcoming ? "text-white/80" : homeWin ? "font-semibold text-white" : "text-white/70",
                ].join(" ")}
              >
                {match.home.name}
              </span>
            </div>
            {!upcoming && <Score value={match.homeScore} live={isLive} dim={awayWin} />}
          </div>

          {/* away row */}
          <div className="mt-1.5 flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2.5">
              <TeamBadge team={match.away} />
              <span
                className={[
                  "truncate text-sm",
                  upcoming ? "text-white/80" : awayWin ? "font-semibold text-white" : "text-white/70",
                ].join(" ")}
              >
                {match.away.name}
              </span>
            </div>
            {!upcoming && <Score value={match.awayScore} live={isLive} dim={homeWin} />}
          </div>

          {match.note && <p className="mt-1.5 text-[11px] text-white/35">{match.note}</p>}
        </div>

        <ChevronDown
          className={`h-4 w-4 shrink-0 text-white/25 transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </div>

      {expanded && <MatchDetail match={match} />}
    </div>
  )
}
