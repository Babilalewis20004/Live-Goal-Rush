"use client"

import { ChevronDown } from "lucide-react"
import Link from "next/link"
import { useState } from "react"
import type { CompetitionOut, MatchSummary } from "@/types/api"
import { MatchCard } from "./match-card"
import { LeagueLogo } from "./league-logo"
import { LiveIndicator } from "./ui/live-indicator"

export function LeagueSection({
  competition,
  matches,
}: {
  competition: CompetitionOut
  matches: MatchSummary[]
}) {
  const [open, setOpen] = useState(true)
  const liveCount = matches.filter((m) => m.status === "live" || m.status === "halftime").length

  return (
    <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md">
      <div className="flex w-full items-center gap-3 px-4 py-3">
        <Link href={`/competition/${competition.id}`} className="flex min-w-0 flex-1 items-center gap-3">
          <LeagueLogo name={competition.name} logoUrl={competition.logo_url} size={28} />
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-sm font-semibold text-white hover:underline">{competition.name}</h2>
            {competition.country && <p className="text-[11px] text-white/40">{competition.country}</p>}
          </div>
        </Link>
        {liveCount > 0 && (
          <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-400">
            <LiveIndicator />
            {liveCount} live
          </span>
        )}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={open ? "Collapse competition" : "Expand competition"}
          className="shrink-0 rounded-full p-1 text-white/40 transition-colors hover:bg-white/[0.06] hover:text-white"
        >
          <ChevronDown className={`h-4 w-4 transition-transform ${open ? "" : "-rotate-90"}`} />
        </button>
      </div>

      {open && (
        <div className="divide-y divide-white/[0.06] border-t border-white/[0.06]">
          {matches.map((match) => (
            <MatchCard key={match.id} match={match} />
          ))}
        </div>
      )}
    </section>
  )
}
