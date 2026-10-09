import { AdSlot } from "@/components/analytics/ad-slot"
import type { Metadata } from "next"
import { notFound } from "next/navigation"
import Image from "next/image"
import Link from "next/link"
import { cache } from "react"

import { AnimatedBackground } from "@/components/animated-background"
import { ArticleBody } from "@/components/news/article-body"
import { Discuss } from "@/components/community/discuss"
import { ArticleCard } from "@/components/news/article-card"
import { Gallery } from "@/components/news/gallery"
import { ShareButton } from "@/components/news/share-button"
import { TrackView } from "@/components/news/track-view"
import { MatchCard } from "@/components/match-card"
import { TeamBadge } from "@/components/team-badge"
import { api, ApiError } from "@/lib/api"
import { formatArticleDate, newsHref } from "@/lib/news"
import { absoluteUrl, articleJsonLd, articleMetadata, jsonLdScript } from "@/lib/seo"

export const dynamic = "force-dynamic"

// One fetch per request even though both generateMetadata and the page need it.
const loadArticle = cache(async (slug: string) => {
  try {
    return await api.getArticle(slug)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
})

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params
  const article = await loadArticle(slug)
  if (!article) return { title: "Article not found", robots: { index: false, follow: false } }
  return articleMetadata(article)
}

const CHIP =
  "inline-flex min-h-8 items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-3 text-xs text-white/80 hover:bg-white/[0.07] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"

export default async function ArticlePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const article = await loadArticle(slug)
  if (!article) notFound()

  const related = await api.getRelatedArticles(slug, 4).catch(() => [])
  const url = absoluteUrl(`/article/${article.slug}`)
  const hasEntities =
    article.teams.length > 0 || article.players.length > 0 || article.competitions.length > 0

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript(articleJsonLd(article)) }} />
      <TrackView entity="article" id={article.slug} />

      <article className="mx-auto max-w-2xl px-4 pb-16 pt-6">
        <Link href="/news" className="text-xs text-white/50 hover:text-white/80">
          ← All news
        </Link>

        <header className="mt-4">
          {article.category && (
            <Link
              href={newsHref({ category: article.category.slug })}
              className="text-[11px] font-semibold uppercase tracking-wide text-emerald-300 hover:underline"
            >
              {article.category.name}
            </Link>
          )}
          <h1 className="mt-1 text-2xl font-bold leading-tight text-white sm:text-3xl">{article.title}</h1>
          <p className="mt-2 text-xs text-white/50">
            {article.published_at && <time dateTime={article.published_at}>{formatArticleDate(article.published_at)}</time>}
            {article.author_name && <span> · By {article.author_name}</span>}
          </p>
          <div className="mt-3">
            <ShareButton url={url} title={article.title} label="Share article" />
          </div>
        </header>

        {article.featured_image_url && (
          <figure className="relative mt-5 aspect-[16/9] overflow-hidden rounded-2xl bg-white/[0.04]">
            <Image
              src={article.featured_image_url}
              alt={article.featured_image_alt || article.title}
              fill
              priority
              unoptimized
              sizes="(min-width: 768px) 672px, 100vw"
              className="object-cover"
            />
          </figure>
        )}

        <div className="mt-6">
          {article.excerpt && <p className="mb-5 text-base font-medium text-white/90">{article.excerpt}</p>}
          <ArticleBody html={article.content} />
        </div>

        <Gallery images={article.gallery} />

        {article.tags.length > 0 && (
          <section aria-label="Tags" className="mt-6">
            <ul className="flex flex-wrap gap-2">
              {article.tags.map((tag) => (
                <li key={tag.id}>
                  <Link href={newsHref({ tag: tag.slug })} className={CHIP}>
                    #{tag.name}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        {hasEntities && (
          <section aria-labelledby="about-heading" className="mt-8">
            <h2 id="about-heading" className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/40">
              In this story
            </h2>
            <ul className="flex flex-wrap gap-2">
              {article.teams.map((team) => (
                <li key={`t${team.id}`}>
                  <Link href={`/team/${team.id}`} className={CHIP}>
                    <TeamBadge name={team.name} shortName={team.short_name} logoUrl={team.logo_url} size={16} />
                    {team.name}
                  </Link>
                </li>
              ))}
              {article.players.map((player) => (
                <li key={`p${player.id}`}>
                  <Link href={`/player/${player.id}`} className={CHIP}>
                    {player.name}
                  </Link>
                </li>
              ))}
              {article.competitions.map((competition) => (
                <li key={`c${competition.id}`}>
                  <Link href={`/competition/${competition.id}`} className={CHIP}>
                    {competition.name}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        {article.matches.length > 0 && (
          <section aria-labelledby="matches-heading" className="mt-6">
            <h2 id="matches-heading" className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/40">
              Related matches
            </h2>
            <div className="divide-y divide-white/[0.06] overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.03]">
              {article.matches.map((match) => (
                <MatchCard key={match.id} match={match} />
              ))}
            </div>
          </section>
        )}

        <AdSlot placement="news" />

        <section aria-label="Reactions and comments" className="mt-10 border-t border-white/[0.08] pt-6">
          <Discuss targetType="article" targetId={article.id} />
        </section>

        {related.length > 0 && (
          <section aria-labelledby="related-heading" className="mt-10">
            <h2 id="related-heading" className="mb-3 text-sm font-semibold text-white">
              Related articles
            </h2>
            <ul className="space-y-3">
              {related.map((item) => (
                <li key={item.id}>
                  <ArticleCard article={item} />
                </li>
              ))}
            </ul>
          </section>
        )}
      </article>
    </main>
  )
}
