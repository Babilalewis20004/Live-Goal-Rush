"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import Link from "next/link"
import { ChevronLeft, ChevronRight, Flame } from "lucide-react"
import type { MatchSummary } from "@/types/api"
import { TeamBadge } from "./team-badge"
import { LeagueLogo } from "./league-logo"
import { LiveIndicator } from "./ui/live-indicator"

function statusLabel(m: MatchSummary) {
  if (m.status === "halftime") return "HT"
  if (m.status === "live") return `${m.minute}'`
  return ""
}

export function HighlightCarousel({ matches }: { matches: MatchSummary[] }) {
  const [index, setIndex] = useState(0)
  const [paused, setPaused] = useState(false)
  const trackRef = useRef<HTMLDivElement>(null)

  const count = matches.length

  const scrollTo = useCallback(
    (i: number) => {
      const track = trackRef.current
      if (!track) return
      const clamped = (i + count) % count
      const child = track.children[clamped] as HTMLElement | undefined
      if (child) track.scrollTo({ left: child.offsetLeft, behavior: "smooth" })
    },
    [count],
  )

  useEffect(() => {
    const track = trackRef.current
    if (!track) return
    let raf = 0
    const onScroll = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const children = Array.from(track.children) as HTMLElement[]
        const center = track.scrollLeft + track.clientWidth / 2
        let nearest = 0
        let min = Infinity
        children.forEach((c, i) => {
          const cCenter = c.offsetLeft + c.offsetWidth / 2
          const d = Math.abs(cCenter - center)
          if (d < min) {
            min = d
            nearest = i
          }
        })
        setIndex(nearest)
      })
    }
    track.addEventListener("scroll", onScroll, { passive: true })
    return () => {
      track.removeEventListener("scroll", onScroll)
      cancelAnimationFrame(raf)
    }
  }, [])

  useEffect(() => {
    if (paused || count <= 1) return
    const id = setInterval(() => scrollTo(index + 1), 4000)
    return () => clearInterval(id)
  }, [index, paused, count, scrollTo])

  if (count === 0) return null

  return (
    <section
      aria-label="Match highlights"
      className="mb-4"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onTouchStart={() => setPaused(true)}
    >
      <div className="mb-2 flex items-center justify-between px-1">
        <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-white/60">
          <Flame className="h-3.5 w-3.5 text-amber-400" />
          Highlights
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="Previous highlight"
            onClick={() => scrollTo(index - 1)}
            className="flex h-6 w-6 items-center justify-center rounded-full border border-white/10 bg-white/[0.03] text-white/60 transition-colors hover:bg-white/[0.08] hover:text-white"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label="Next highlight"
            onClick={() => scrollTo(index + 1)}
            className="flex h-6 w-6 items-center justify-center rounded-full border border-white/10 bg-white/[0.03] text-white/60 transition-colors hover:bg-white/[0.08] hover:text-white"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div
        ref={trackRef}
        className="ls-no-scrollbar flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-smooth pb-1"
      >
        {matches.map((m) => (
          <HighlightCard key={m.id} match={m} />
        ))}
      </div>

      <div className="mt-2 flex items-center justify-center gap-1.5">
        {matches.map((m, i) => (
          <button
            key={m.id}
            type="button"
            aria-label={`Go to highlight ${i + 1}`}
            onClick={() => scrollTo(i)}
            className={[
              "h-1.5 rounded-full transition-all",
              i === index ? "w-5 bg-emerald-400" : "w-1.5 bg-white/20 hover:bg-white/40",
            ].join(" ")}
          />
        ))}
      </div>
    </section>
  )
}

function HighlightCard({ match: m }: { match: MatchSummary }) {
  return (
    <Link
      href={`/match/${m.id}`}
      className="relative w-full min-w-full snap-center overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.04] p-4"
      style={{ boxShadow: `inset 0 1px 0 0 rgba(255,255,255,0.05)` }}
    >
      <div className="relative mb-3 flex items-center justify-between">
        <span className="flex items-center gap-1.5 rounded-full bg-white/[0.06] py-0.5 pl-1 pr-2.5 text-[10px] font-semibold uppercase tracking-wide text-white/90">
          <LeagueLogo name={m.competition.name} logoUrl={m.competition.logo_url} size={16} />
          {m.competition.name}
        </span>
        <span className="flex items-center gap-1.5 text-xs font-bold text-emerald-400">
          <LiveIndicator />
          {statusLabel(m)}
        </span>
      </div>

      <div className="relative flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-1 flex-col items-center gap-1.5">
          <TeamBadge name={m.home_team.name} shortName={m.home_team.short_name} logoUrl={m.home_team.logo_url} size={40} />
          <span className="truncate text-center text-xs font-medium text-white/80">{m.home_team.name}</span>
        </div>

        <div className="flex shrink-0 flex-col items-center px-2">
          <div className="flex items-center gap-2 text-3xl font-bold tabular-nums text-white">
            <span className={m.home_score >= m.away_score ? "" : "text-white/40"}>{m.home_score}</span>
            <span className="text-white/30">-</span>
            <span className={m.away_score >= m.home_score ? "" : "text-white/40"}>{m.away_score}</span>
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col items-center gap-1.5">
          <TeamBadge name={m.away_team.name} shortName={m.away_team.short_name} logoUrl={m.away_team.logo_url} size={40} />
          <span className="truncate text-center text-xs font-medium text-white/80">{m.away_team.name}</span>
        </div>
      </div>
    </Link>
  )
}
