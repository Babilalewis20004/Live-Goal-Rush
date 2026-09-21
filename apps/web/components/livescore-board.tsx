"use client"

import { useMemo, useState } from "react"
import type { MatchSummary } from "@/types/api"
import { groupByCompetition } from "@/lib/format"
import { LeagueSection } from "./league-section"
import { LivescoreHeader } from "./livescore-header"
import { HighlightCarousel } from "./highlight-carousel"
import { EmptyState } from "./ui/empty-state"

type Filter = "live" | "today" | "upcoming" | "finished"

const FILTERS: { key: Filter; label: string }[] = [
  { key: "live", label: "Live" },
  { key: "today", label: "Today" },
  { key: "upcoming", label: "Upcoming" },
  { key: "finished", label: "Finished" },
]

export function LivescoreBoard({
  live,
  today,
  upcoming,
}: {
  live: MatchSummary[]
  today: MatchSummary[]
  upcoming: MatchSummary[]
}) {
  const [filter, setFilter] = useState<Filter>("live")

  const finished = useMemo(() => today.filter((m) => m.status === "finished"), [today])

  const active = useMemo(() => {
    switch (filter) {
      case "live":
        return live
      case "today":
        return today
      case "upcoming":
        return upcoming
      case "finished":
        return finished
    }
  }, [filter, live, today, upcoming, finished])

  const groups = useMemo(() => groupByCompetition(active), [active])

  return (
    <>
      <LivescoreHeader liveCount={live.length} />

      <div className="mx-auto max-w-2xl px-4 pb-16 pt-4">
        <HighlightCarousel matches={live} />

        <div className="sticky top-[65px] z-10 -mx-1 mb-4 flex gap-1.5 overflow-x-auto px-1 py-1">
          {FILTERS.map((f) => {
            const isActive = filter === f.key
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={[
                  "flex items-center gap-1.5 whitespace-nowrap rounded-full px-4 py-1.5 text-sm font-medium transition-all",
                  isActive
                    ? "bg-emerald-400 text-[#070b09] shadow-lg shadow-emerald-500/25"
                    : "border border-white/10 bg-white/[0.03] text-white/60 hover:bg-white/[0.06] hover:text-white",
                ].join(" ")}
              >
                {f.key === "live" && (
                  <span
                    className={`ls-live-dot h-1.5 w-1.5 rounded-full ${isActive ? "bg-[#070b09]" : "bg-emerald-400"}`}
                  />
                )}
                {f.label}
              </button>
            )
          })}
        </div>

        <div className="space-y-3">
          {groups.map(({ competition, matches }) => (
            <LeagueSection key={competition.id} competition={competition} matches={matches} />
          ))}

          {groups.length === 0 && <EmptyState message="No matches in this category right now." />}
        </div>

        <p className="mt-8 text-center text-[11px] text-white/25">
          Kickoff times shown in UTC · Major leagues only
        </p>
      </div>
    </>
  )
}
