import type { Metadata } from "next"
import { headers } from "next/headers"
import Link from "next/link"

import { AnimatedBackground } from "@/components/animated-background"
import { CompetitionCard } from "@/components/competition-card"
import { MatchCard } from "@/components/match-card"
import { ArticleCard } from "@/components/news/article-card"
import { SearchBox } from "@/components/search/search-box"
import { SearchHome } from "@/components/search/search-home"
import { TrackedLink } from "@/components/search/tracked-link"
import { TeamBadge } from "@/components/team-badge"
import { EmptyState } from "@/components/ui/empty-state"
import { ErrorState } from "@/components/ui/error-state"
import { api, ApiError } from "@/lib/api"
import type { SearchResults } from "@/types/api"

export const dynamic = "force-dynamic"

// Search result pages are infinite, personal-ish and duplicate content: keep
// them out of the index (links on them are still followed).
export const metadata: Metadata = {
  title: "Search",
  robots: { index: false, follow: true },
}

const ROW =
  "flex items-center gap-3 rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 transition-colors hover:bg-white/[0.06] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"

function Group({ id, title, count, children }: { id: string; title: string; count: number; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id}>
      <h2 id={id} className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/40">
        {title} <span className="font-normal text-white/30">({count})</span>
      </h2>
      {children}
    </section>
  )
}

export default async function SearchPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q = "" } = await searchParams
  const query = q.trim().slice(0, 100)
  let results: SearchResults | null = null
  let failure: string | null = null
  if (query) {
    try {
      const visitor = (await headers()).get("x-forwarded-for")?.split(",")[0]?.trim() || undefined
      results = await api.search(query, visitor)
    } catch (error) {
      failure =
        error instanceof ApiError && error.status === 429
          ? "You're searching a little fast — wait a moment and try again."
          : "Search is unavailable right now. Please try again."
    }
  }
  const total = results
    ? results.teams.length + results.competitions.length + results.players.length + results.matches.length + results.articles.length
    : 0

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-2xl px-4 pb-16 pt-6">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>

        <h1 className="mb-4 mt-4 text-lg font-bold text-white">Search</h1>
        <SearchBox initialQuery={query} />

        <div className="mt-6 space-y-6">
          {!query && <SearchHome />}
          {!query && <EmptyState message="Search for teams, players, competitions, matches or news." />}
          {failure && <ErrorState message={failure} />}
          {results && total === 0 && (
            <EmptyState message={`No results for "${query}". Check the spelling or try a shorter name.`} />
          )}

          {results && total > 0 && (
            <p role="status" className="text-xs text-white/40">
              {total} result{total === 1 ? "" : "s"} for &ldquo;{query}&rdquo;
            </p>
          )}

          {results && results.teams.length > 0 && (
            <Group id="g-teams" title="Teams" count={results.teams.length}>
              <ul className="space-y-2">
                {results.teams.map((team) => (
                  <li key={team.id}>
                    <TrackedLink href={`/team/${team.id}`} query={query} entity="team" entityId={team.id} className={ROW}>
                      <TeamBadge name={team.name} shortName={team.short_name} logoUrl={team.logo_url} />
                      <span className="text-sm text-white">{team.name}</span>
                    </TrackedLink>
                  </li>
                ))}
              </ul>
            </Group>
          )}

          {results && results.players.length > 0 && (
            <Group id="g-players" title="Players" count={results.players.length}>
              <ul className="space-y-2">
                {results.players.map((player) => (
                  <li key={player.id}>
                    <TrackedLink
                      href={`/player/${player.id}`}
                      query={query}
                      entity="player"
                      entityId={player.id}
                      className={`${ROW} justify-between`}
                    >
                      <span className="text-sm text-white">{player.name}</span>
                      {player.position && <span className="text-xs text-white/40">{player.position}</span>}
                    </TrackedLink>
                  </li>
                ))}
              </ul>
            </Group>
          )}

          {results && results.competitions.length > 0 && (
            <Group id="g-competitions" title="Competitions" count={results.competitions.length}>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {results.competitions.map((competition) => (
                  <CompetitionCard key={competition.id} competition={competition} />
                ))}
              </div>
            </Group>
          )}

          {results && results.articles.length > 0 && (
            <Group id="g-news" title="News" count={results.articles.length}>
              <ul className="space-y-3">
                {results.articles.map((article) => (
                  <li key={article.id}>
                    <ArticleCard article={article} />
                  </li>
                ))}
              </ul>
            </Group>
          )}

          {results && results.matches.length > 0 && (
            <Group id="g-matches" title="Matches" count={results.matches.length}>
              <div className="divide-y divide-white/[0.06] overflow-hidden rounded-xl border border-white/[0.08] bg-white/[0.03]">
                {results.matches.map((match) => (
                  <MatchCard key={match.id} match={match} />
                ))}
              </div>
            </Group>
          )}
        </div>
      </div>
    </main>
  )
}
