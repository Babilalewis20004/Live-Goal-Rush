"use client"

import { ChevronDown } from "lucide-react"
import { useState } from "react"
import type { League } from "@/lib/matches"
import { MatchCard } from "./match-card"
import { LeagueLogo } from "./league-logo"

export function LeagueSection({ league }: { league: League }) {
  const [open, setOpen] = useState(true)
  const liveCount = league.matches.filter((m) => m.status === "live").length

  return (
    <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-white/[0.03]"
      >
        <LeagueLogo name={league.name} color={league.color} size={28} />
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold text-white">{league.name}</h2>
          <p className="text-[11px] text-white/40">{league.country}</p>
        </div>
        {liveCount > 0 && (
          <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-400">
            <span className="ls-live-dot h-1.5 w-1.5 rounded-full bg-emerald-400" />
            {liveCount} live
          </span>
        )}
        <ChevronDown
          className={`h-4 w-4 text-white/40 transition-transform ${open ? "" : "-rotate-90"}`}
        />
      </button>

      {open && (
        <div className="divide-y divide-white/[0.06] border-t border-white/[0.06]">
          {league.matches.map((match) => (
            <MatchCard key={match.id} match={match} />
          ))}
        </div>
      )}
    </section>
  )
}
