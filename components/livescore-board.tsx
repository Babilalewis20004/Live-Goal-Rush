"use client"

import { useMemo, useState } from "react"
import { leagues, type MatchStatus } from "@/lib/matches"
import { LeagueSection } from "./league-section"
import { LivescoreHeader } from "./livescore-header"
import { HighlightCarousel } from "./highlight-carousel"

type Filter = "all" | MatchStatus

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "live", label: "Live" },
  { key: "finished", label: "Finished" },
  { key: "upcoming", label: "Upcoming" },
]

export function LivescoreBoard() {
  const [filter, setFilter] = useState<Filter>("all")

  const liveCount = useMemo(
    () => leagues.reduce((n, l) => n + l.matches.filter((m) => m.status === "live").length, 0),
    [],
  )

  const filtered = useMemo(() => {
    if (filter === "all") return leagues
    return leagues
      .map((l) => ({
        ...l,
        matches: l.matches.filter((m) =>
          filter === "live" ? m.status === "live" || m.status === "halftime" : m.status === filter,
        ),
      }))
      .filter((l) => l.matches.length > 0)
  }, [filter])

  return (
    <>
      <LivescoreHeader liveCount={liveCount} />

      <div className="mx-auto max-w-2xl px-4 pb-16 pt-4">
        <HighlightCarousel leagues={leagues} />

        {/* filter tabs */}
        <div className="sticky top-[65px] z-10 -mx-1 mb-4 flex gap-1.5 overflow-x-auto px-1 py-1">
          {FILTERS.map((f) => {
            const active = filter === f.key
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={[
                  "flex items-center gap-1.5 whitespace-nowrap rounded-full px-4 py-1.5 text-sm font-medium transition-all",
                  active
                    ? "bg-emerald-400 text-[#070b09] shadow-lg shadow-emerald-500/25"
                    : "border border-white/10 bg-white/[0.03] text-white/60 hover:bg-white/[0.06] hover:text-white",
                ].join(" ")}
              >
                {f.key === "live" && (
                  <span
                    className={`ls-live-dot h-1.5 w-1.5 rounded-full ${active ? "bg-[#070b09]" : "bg-emerald-400"}`}
                  />
                )}
                {f.label}
              </button>
            )
          })}
        </div>

        <div className="space-y-3">
          {filtered.map((league) => (
            <LeagueSection key={league.id} league={league} />
          ))}

          {filtered.length === 0 && (
            <div className="rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-12 text-center text-sm text-white/40">
              No matches in this category right now.
            </div>
          )}
        </div>

        <p className="mt-8 text-center text-[11px] text-white/25">
          Scores are simulated for demo purposes · Major leagues only
        </p>
      </div>
    </>
  )
}
