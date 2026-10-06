"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"
import { SEASON_POLL } from "@/lib/seasons"
import type { CompetitionSeasonsOut, StandingEntry, TopScorersOut } from "@/types/api"

export interface SeasonViewState {
  /** `null` = the current (latest stored) season, as server-rendered. */
  season: string | null
  select: (season: string | null) => void
  standings: StandingEntry[] | null
  topScorers: TopScorersOut | null
  /** A past season was requested and is still being fetched by the worker. */
  loading: boolean
  /** The re-checks ran out without data (provider has no such season). */
  gaveUp: boolean
}

/** Standings + top scorers for the selected season. The initial (current)
 * season comes from the server render; picking another season fetches it, and
 * when the backend answers empty for a season it is still syncing in the
 * background, re-checks a few times before giving up. */
export function useSeasonView(
  competitionId: number,
  initial: { standings: StandingEntry[] | null; topScorers: TopScorersOut | null },
  info: CompetitionSeasonsOut | null,
): SeasonViewState {
  const [season, setSeason] = useState<string | null>(null)
  const [standings, setStandings] = useState(initial.standings)
  const [topScorers, setTopScorers] = useState(initial.topScorers)
  const [loading, setLoading] = useState(false)
  const [gaveUp, setGaveUp] = useState(false)
  const run = useRef(0)
  // Primitives, not the `info` object: a caller passing a fresh object each
  // render must not restart the fetch (and its polling) every time.
  const historical = info?.historical_supported ?? false
  const stored = season !== null && (info?.seasons.includes(season) ?? false)

  const select = useCallback((next: string | null) => {
    run.current += 1
    // flip to the loading state in the same render as the new selection, so the
    // previous season's table is never shown under the new season's name
    setLoading(next !== null)
    setGaveUp(false)
    setSeason(next)
  }, [])

  useEffect(() => {
    if (season === null) {
      return
    }
    const mine = run.current
    const timers: ReturnType<typeof setTimeout>[] = []

    async function load(attempt: number) {
      try {
        const [s, t] = await Promise.all([
          api.getStandings(competitionId, season ?? undefined),
          api.getTopScorers(competitionId, season ?? undefined).catch(() => null),
        ])
        if (run.current !== mine) return
        setStandings(s)
        setTopScorers(t)
        const empty = s.length === 0
        if (!empty || stored || !historical) {
          setLoading(false)
          setGaveUp(empty)
        } else if (attempt + 1 < SEASON_POLL.attempts) {
          timers.push(setTimeout(() => void load(attempt + 1), SEASON_POLL.intervalMs))
        } else {
          setLoading(false)
          setGaveUp(true)
        }
      } catch {
        if (run.current === mine) {
          setLoading(false)
          setGaveUp(true)
        }
      }
    }

    // The timer keeps the first state updates out of the effect body itself.
    timers.push(
      setTimeout(() => {
        if (run.current !== mine) return
        setLoading(true)
        setGaveUp(false)
        void load(0)
      }, 0),
    )
    return () => timers.forEach(clearTimeout)
  }, [season, competitionId, historical, stored])

  // Back on the current season: show what the server rendered, untouched.
  const current = season === null
  return {
    season,
    select,
    standings: current ? initial.standings : standings,
    topScorers: current ? initial.topScorers : topScorers,
    loading: current ? false : loading,
    gaveUp: current ? false : gaveUp,
  }
}
