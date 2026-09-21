"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { ChevronLeft, ChevronRight, Flame } from "lucide-react"
import type { League, Match } from "@/lib/matches"
import { TeamBadge } from "./team-badge"
import { LeagueLogo } from "./league-logo"

type Highlight = {
  match: Match
  leagueName: string
  leagueColor: string
}

function buildHighlights(leagues: League[]): Highlight[] {
  const rank = (m: Match) => (m.status === "live" ? 0 : m.status === "halftime" ? 1 : 2)
  return leagues
    .flatMap((l) => l.matches.map((match) => ({ match, leagueName: l.name, leagueColor: l.color })))
    .filter((h) => h.match.status === "live" || h.match.status === "halftime")
    .sort((a, b) => rank(a.match) - rank(b.match))
}

function statusLabel(m: Match) {
  if (m.status === "halftime") return "HT"
  if (m.status === "live") return `${m.minute}'`
  return ""
}

export function HighlightCarousel({ leagues }: { leagues: League[] }) {
  const highlights = buildHighlights(leagues)
  const [index, setIndex] = useState(0)
  const [paused, setPaused] = useState(false)
  const trackRef = useRef<HTMLDivElement>(null)

  const count = highlights.length

  const scrollTo = useCallback((i: number) => {
    const track = trackRef.current
    if (!track) return
    const clamped = (i + count) % count
    const child = track.children[clamped] as HTMLElement | undefined
    if (child) track.scrollTo({ left: child.offsetLeft, behavior: "smooth" })
  }, [count])

  // keep index synced with manual scroll
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

  // auto-advance
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
        {highlights.map((h) => (
          <HighlightCard key={h.match.id} highlight={h} />
        ))}
      </div>

      <div className="mt-2 flex items-center justify-center gap-1.5">
        {highlights.map((h, i) => (
          <button
            key={h.match.id}
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

function HighlightCard({ highlight }: { highlight: Highlight }) {
  const { match: m, leagueName, leagueColor } = highlight
  return (
    <article
      className="relative w-full min-w-full snap-center overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.04] p-4"
      style={{ boxShadow: `inset 0 1px 0 0 rgba(255,255,255,0.05)` }}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full opacity-20 blur-2xl"
        style={{ backgroundColor: leagueColor }}
      />
      <div className="relative mb-3 flex items-center justify-between">
        <span
          className="flex items-center gap-1.5 rounded-full py-0.5 pl-1 pr-2.5 text-[10px] font-semibold uppercase tracking-wide text-white/90"
          style={{ backgroundColor: `${leagueColor}55` }}
        >
          <LeagueLogo name={leagueName} color={leagueColor} size={16} />
          {leagueName}
        </span>
        <span className="flex items-center gap-1.5 text-xs font-bold text-emerald-400">
          <span className="ls-live-dot h-1.5 w-1.5 rounded-full bg-emerald-400" />
          {statusLabel(m)}
        </span>
      </div>

      <div className="relative flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-1 flex-col items-center gap-1.5">
          <TeamBadge team={m.home} size={40} />
          <span className="truncate text-center text-xs font-medium text-white/80">{m.home.name}</span>
        </div>

        <div className="flex shrink-0 flex-col items-center px-2">
          <div className="flex items-center gap-2 text-3xl font-bold tabular-nums text-white">
            <span className={m.homeScore >= m.awayScore ? "" : "text-white/40"}>{m.homeScore}</span>
            <span className="text-white/30">-</span>
            <span className={m.awayScore >= m.homeScore ? "" : "text-white/40"}>{m.awayScore}</span>
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col items-center gap-1.5">
          <TeamBadge team={m.away} size={40} />
          <span className="truncate text-center text-xs font-medium text-white/80">{m.away.name}</span>
        </div>
      </div>

      {m.note && <p className="relative mt-3 text-center text-[11px] text-white/40">{m.note}</p>}
    </article>
  )
}
