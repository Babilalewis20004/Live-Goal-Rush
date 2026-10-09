import type { Metadata } from "next"
import { notFound } from "next/navigation"
import Link from "next/link"
import { cache } from "react"
import { AnimatedBackground } from "@/components/animated-background"
import { MatchCard } from "@/components/match-card"
import { PlayerAnalytics } from "@/components/analytics/player-analytics"
import { EntityNews } from "@/components/news/entity-news"
import { ShareButton } from "@/components/news/share-button"
import { TrackView } from "@/components/news/track-view"
import { TeamBadge } from "@/components/team-badge"
import { EmptyState } from "@/components/ui/empty-state"
import { api, ApiError } from "@/lib/api"
import { absoluteUrl, jsonLdScript, playerJsonLd, playerMetadata } from "@/lib/seo"
import type { PlayerMatchStatsOut } from "@/types/api"

export const dynamic = "force-dynamic"

const CARD = "overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md"

async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch {
    return null
  }
}

function matchLine(stats: PlayerMatchStatsOut): string {
  // Only what the provider supplied: a null field is left out, never shown as 0.
  const parts: string[] = []
  if (stats.minutes_played != null) parts.push(`${stats.minutes_played} min`)
  if (stats.goals) parts.push(`${stats.goals} goal${stats.goals === 1 ? "" : "s"}`)
  if (stats.assists) parts.push(`${stats.assists} assist${stats.assists === 1 ? "" : "s"}`)
  if (stats.yellow_cards) parts.push(`${stats.yellow_cards} yellow`)
  if (stats.red_cards) parts.push("red card")
  return parts.join(" · ")
}

const loadPlayer = cache(async (playerId: number) => {
  try {
    return await api.getPlayer(playerId)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
})

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const playerId = Number((await params).id)
  const player = Number.isInteger(playerId) ? await loadPlayer(playerId) : null
  if (!player) return { title: "Player not found", robots: { index: false, follow: false } }
  return playerMetadata(player)
}

export default async function PlayerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const playerId = Number(id)
  if (!Number.isInteger(playerId)) notFound()

  const player = await loadPlayer(playerId)
  if (!player) notFound()
  const [statistics, capabilities, news] = await Promise.all([
    optional(api.getPlayerStatistics(playerId)),
    optional(api.getCapabilities()),
    optional(api.getPlayerNews(playerId)),
  ])
  const profileUnsupported = capabilities?.player_profiles === false

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript(playerJsonLd(player)) }} />
      <TrackView entity="player" id={playerId} />
      <div className="mx-auto max-w-3xl px-4 pb-16 pt-6">
        <div className="flex items-center justify-between">
          <Link href="/" className="text-xs text-white/50 hover:text-white/80">
            ← Back to livescores
          </Link>
          <ShareButton url={absoluteUrl(`/player/${playerId}`)} title={player.name} />
        </div>

        <header className={`${CARD} mt-4 flex items-center gap-4 px-5 py-6`}>
          <div
            aria-hidden="true"
            className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-white/[0.08] text-lg font-bold text-white/70"
          >
            {player.shirt_number ?? player.name.slice(0, 1)}
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-lg font-bold text-white">{player.name}</h1>
            <p className="text-xs text-white/50">
              {[player.position, player.nationality].filter(Boolean).join(" · ") || "Profile details not available"}
            </p>
          </div>
          {player.team && (
            <Link href={`/team/${player.team.id}`} className="flex shrink-0 items-center gap-2 text-xs text-white/70 hover:underline">
              <TeamBadge name={player.team.name} shortName={player.team.short_name} logoUrl={player.team.logo_url} size={28} />
              <span className="hidden sm:inline">{player.team.name}</span>
            </Link>
          )}
        </header>

        {profileUnsupported && (
          <p className="mt-2 text-[11px] text-white/35">
            Detailed player profiles aren&apos;t provided by the current football data provider.
          </p>
        )}

        <section className={`${CARD} mt-4`}>
          <h2 className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">Season statistics</h2>
          {statistics && statistics.seasons.length > 0 ? (
            <table className="w-full text-sm">
              <caption className="sr-only">Season statistics by competition</caption>
              <thead>
                <tr className="text-[11px] uppercase tracking-wide text-white/40">
                  <th scope="col" className="py-2 pl-4 text-left font-medium">Competition</th>
                  <th scope="col" className="w-9 py-2 text-center font-medium"><abbr title="Appearances" className="no-underline">Apps</abbr></th>
                  <th scope="col" className="w-9 py-2 text-center font-medium"><abbr title="Goals" className="no-underline">Gls</abbr></th>
                  <th scope="col" className="w-9 py-2 pr-4 text-center font-medium"><abbr title="Assists" className="no-underline">Ast</abbr></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {statistics.seasons.map((s) => (
                  <tr key={`${s.competition_id}-${s.season}`}>
                    <td className="py-2 pl-4">
                      <Link href={`/competition/${s.competition_id}`} className="text-white/90 hover:underline">
                        {s.competition_name}
                      </Link>
                      <span className="block text-[10px] text-white/40">Season {s.season}</span>
                    </td>
                    <td className="py-2 text-center text-white/60">{s.appearances ?? "–"}</td>
                    <td className="py-2 text-center font-semibold text-white">{s.goals}</td>
                    <td className="py-2 pr-4 text-center text-white/60">{s.assists ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="px-4 py-4">
              <EmptyState message="No season statistics are available for this player." />
            </div>
          )}
        </section>

        <div className="mt-4">
          <PlayerAnalytics playerId={playerId} showSeasons={false} />
        </div>

        <section className={`${CARD} mt-4`}>
          <h2 className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">Recent matches</h2>
          {statistics && statistics.recent_matches.length > 0 ? (
            <ul className="divide-y divide-white/[0.06]">
              {statistics.recent_matches.map((a) => (
                <li key={a.match.id}>
                  <MatchCard match={a.match} />
                  {matchLine(a.stats) && <p className="px-4 pb-3 pl-[4.75rem] text-[11px] text-white/45">{matchLine(a.stats)}</p>}
                </li>
              ))}
            </ul>
          ) : (
            <div className="px-4 py-4">
              <EmptyState message="No match statistics stored for this player yet." />
            </div>
          )}
        </section>

        {news && news.total > 0 && (
          <section aria-labelledby="player-news" className="mt-4">
            <h2 id="player-news" className="mb-3 text-sm font-semibold text-white">
              News
            </h2>
            <EntityNews kind="player" id={playerId} initial={news} />
          </section>
        )}
      </div>
    </main>
  )
}
