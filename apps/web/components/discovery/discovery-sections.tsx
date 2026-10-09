import Link from "next/link"

import { CompetitionCard } from "@/components/competition-card"
import { MatchCard } from "@/components/match-card"
import { ArticleCard } from "@/components/news/article-card"
import { TeamBadge } from "@/components/team-badge"
import { trendLabel } from "@/lib/news"
import type { DiscoveryHome } from "@/types/api"

const CARD = "overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-md"

function Section({
  id,
  title,
  href,
  hrefLabel,
  children,
}: {
  id: string
  title: string
  href?: string
  hrefLabel?: string
  children: React.ReactNode
}) {
  return (
    <section aria-labelledby={id} className="mt-8">
      <div className="mb-3 flex items-center justify-between">
        <h2 id={id} className="text-sm font-semibold text-white">
          {title}
        </h2>
        {href && (
          <Link href={href} className="text-xs text-white/50 hover:text-white/80">
            {hrefLabel ?? "See all"} →
          </Link>
        )}
      </div>
      {children}
    </section>
  )
}

/** The public half of the discovery home, rendered under the live board.
 * Everything here comes from `/discovery/home`; a section with no data is
 * simply not rendered (no placeholder rankings). Trending means "getting
 * attention", and the labels say why in words, never as a performance claim. */
export function DiscoverySections({ home }: { home: DiscoveryHome | null }) {
  if (!home) return null
  const { featured_articles, latest_articles, latest_results, trending_teams, trending_players, trending_articles, popular_competitions } = home

  const lead = featured_articles[0] ?? latest_articles[0]
  const newsList = latest_articles.filter((a) => a.id !== lead?.id).slice(0, 4)

  return (
    <div className="mx-auto max-w-2xl px-4 pb-16">
      {lead && (
        <Section id="home-news" title="Football news" href="/news">
          <div className="space-y-3">
            <ArticleCard article={lead} variant="hero" />
            {newsList.length > 0 && (
              <ul className={`${CARD} divide-y divide-white/[0.06]`}>
                {newsList.map((article) => (
                  <li key={article.id}>
                    <ArticleCard article={article} variant="compact" />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Section>
      )}

      {latest_results.length > 0 && (
        <Section id="home-results" title="Latest results">
          <div className={`${CARD} divide-y divide-white/[0.06]`}>
            {latest_results.slice(0, 5).map((match) => (
              <MatchCard key={match.id} match={match} />
            ))}
          </div>
        </Section>
      )}

      {trending_teams.length > 0 && (
        <Section id="home-trending-teams" title="Trending teams">
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {trending_teams.map(({ item, signals }) => (
              <li key={item.id}>
                <Link
                  href={`/team/${item.id}`}
                  className="flex items-center gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 transition-colors hover:bg-white/[0.06] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
                >
                  <TeamBadge name={item.name} shortName={item.short_name} logoUrl={item.logo_url} size={32} />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold text-white">{item.name}</span>
                    <span className="block text-[11px] text-white/40">{trendLabel(signals)}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {trending_players.length > 0 && (
        <Section id="home-trending-players" title="Trending players">
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {trending_players.map(({ item, signals }) => (
              <li key={item.id}>
                <Link
                  href={`/player/${item.id}`}
                  className="flex items-center justify-between gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 transition-colors hover:bg-white/[0.06] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold text-white">{item.name}</span>
                    <span className="block text-[11px] text-white/40">{trendLabel(signals)}</span>
                  </span>
                  {item.position && <span className="shrink-0 text-[11px] text-white/40">{item.position}</span>}
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {trending_articles.length > 0 && (
        <Section id="home-trending-news" title="Trending in news">
          <ul className={`${CARD} divide-y divide-white/[0.06]`}>
            {trending_articles.map(({ item }) => (
              <li key={item.id}>
                <ArticleCard article={item} variant="compact" />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {popular_competitions.length > 0 && (
        <Section id="home-competitions" title="Popular competitions" href="/competitions">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {popular_competitions.map((competition) => (
              <CompetitionCard key={competition.id} competition={competition} />
            ))}
          </div>
        </Section>
      )}
    </div>
  )
}
