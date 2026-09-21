"use client"

import { useState } from "react"
import { ArrowRightLeft, MapPin } from "lucide-react"
import type { Match, MatchEvent } from "@/lib/matches"

function EventIcon({ type }: { type: MatchEvent["type"] }) {
  if (type === "yellow") return <span className="h-3.5 w-2.5 rounded-[2px] bg-amber-400" />
  if (type === "red") return <span className="h-3.5 w-2.5 rounded-[2px] bg-red-500" />
  if (type === "sub") return <ArrowRightLeft className="h-3.5 w-3.5 text-emerald-400" />
  // goal / penalty / own-goal
  const isOwn = type === "own-goal"
  return (
    <span
      className={[
        "flex h-4 w-4 items-center justify-center rounded-full text-[8px] font-bold",
        isOwn ? "bg-red-500/20 text-red-400" : "bg-white text-[#070b09]",
      ].join(" ")}
      aria-hidden
    >
      {type === "penalty" ? "P" : "⚽"}
    </span>
  )
}

function EventRow({ event }: { event: MatchEvent }) {
  const isHome = event.team === "home"
  const isGoal = event.type === "goal" || event.type === "penalty" || event.type === "own-goal"

  const content = (
    <div className={["flex items-center gap-2", isHome ? "flex-row" : "flex-row-reverse"].join(" ")}>
      <EventIcon type={event.type} />
      <div className={isHome ? "text-left" : "text-right"}>
        <p className={["text-xs", isGoal ? "font-semibold text-white" : "text-white/70"].join(" ")}>{event.player}</p>
        {event.detail && <p className="text-[10px] text-white/40">{event.detail}</p>}
      </div>
    </div>
  )

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1">{isHome && content}</div>
      <span className="shrink-0 rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-white/60">
        {event.minute}&apos;
      </span>
      <div className="flex-1">{!isHome && content}</div>
    </div>
  )
}

function StatBar({ label, home, away, percent }: { label: string; home: number; away: number; percent?: boolean }) {
  const total = home + away || 1
  const homePct = (home / total) * 100
  const homeLeads = home >= away
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px] tabular-nums">
        <span className={homeLeads ? "font-semibold text-white" : "text-white/60"}>
          {home}
          {percent ? "%" : ""}
        </span>
        <span className="text-white/40">{label}</span>
        <span className={!homeLeads ? "font-semibold text-white" : "text-white/60"}>
          {away}
          {percent ? "%" : ""}
        </span>
      </div>
      <div className="flex h-1.5 gap-1 overflow-hidden rounded-full">
        <div className="flex justify-end overflow-hidden rounded-l-full bg-white/[0.06]" style={{ width: `${homePct}%` }}>
          <span className={["h-full w-full rounded-l-full", homeLeads ? "bg-emerald-400" : "bg-white/30"].join(" ")} />
        </div>
        <div className="flex-1 overflow-hidden rounded-r-full bg-white/[0.06]">
          <span
            className={["block h-full rounded-r-full", !homeLeads ? "bg-sky-400" : "bg-white/30"].join(" ")}
            style={{ width: `${100 - homePct}%` }}
          />
        </div>
      </div>
    </div>
  )
}

export function MatchDetail({ match }: { match: Match }) {
  const hasEvents = match.events && match.events.length > 0
  const hasStats = match.stats && match.stats.length > 0
  const [tab, setTab] = useState<"summary" | "stats">(hasEvents ? "summary" : "stats")

  if (!hasEvents && !hasStats) {
    return (
      <div className="border-t border-white/[0.06] px-4 py-4 text-center text-xs text-white/40">
        {match.venue ? (
          <span className="inline-flex items-center gap-1.5">
            <MapPin className="h-3.5 w-3.5" />
            {match.venue}
          </span>
        ) : (
          "No match data available yet."
        )}
      </div>
    )
  }

  return (
    <div className="border-t border-white/[0.06] bg-black/20 px-4 py-3">
      {/* mini tabs */}
      <div className="mb-3 flex gap-1">
        {hasEvents && (
          <button
            type="button"
            onClick={() => setTab("summary")}
            className={[
              "rounded-full px-3 py-1 text-[11px] font-medium transition-colors",
              tab === "summary" ? "bg-white/10 text-white" : "text-white/50 hover:text-white/80",
            ].join(" ")}
          >
            Summary
          </button>
        )}
        {hasStats && (
          <button
            type="button"
            onClick={() => setTab("stats")}
            className={[
              "rounded-full px-3 py-1 text-[11px] font-medium transition-colors",
              tab === "stats" ? "bg-white/10 text-white" : "text-white/50 hover:text-white/80",
            ].join(" ")}
          >
            Statistics
          </button>
        )}
      </div>

      {tab === "summary" && hasEvents && (
        <div className="space-y-2.5">
          {match.events!.map((event, i) => (
            <EventRow key={i} event={event} />
          ))}
        </div>
      )}

      {tab === "stats" && hasStats && (
        <div className="space-y-2.5">
          {match.stats!.map((s) => (
            <StatBar key={s.label} label={s.label} home={s.home} away={s.away} percent={s.percent} />
          ))}
        </div>
      )}

      {match.venue && (
        <p className="mt-3 flex items-center gap-1.5 border-t border-white/[0.06] pt-2.5 text-[10px] text-white/35">
          <MapPin className="h-3 w-3" />
          {match.venue}
        </p>
      )}
    </div>
  )
}
