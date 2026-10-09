import type { Metadata } from "next"

import type {
  ArticleDetail,
  CompetitionOut,
  MatchDetail,
  MatchSummary,
  PlayerDetail,
  TeamDetail,
} from "@/types/api"

export const SITE_NAME = "LivePitch"

/** Canonical origin for every public URL (canonical links, Open Graph,
 * sitemap, structured data). Set `NEXT_PUBLIC_SITE_URL` in production; the
 * default is only right for local development. */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/+$/, "")

/** `/article/x` -> `https://site/article/x`. One path always maps to one URL
 * (no query strings, no trailing slash), which is what keeps canonicals unique. */
export function absoluteUrl(path: string): string {
  const clean = path.split(/[?#]/)[0].replace(/\/+$/, "")
  return `${SITE_URL}${clean.startsWith("/") ? clean : `/${clean}`}`
}

export function truncate(text: string, max: number): string {
  const flat = text.replace(/\s+/g, " ").trim()
  if (flat.length <= max) return flat
  return `${flat.slice(0, max - 1).replace(/\s+\S*$/, "").trimEnd()}…`
}

/** Serialises structured data for a `<script type="application/ld+json">`.
 * `<` is escaped so a title containing `</script>` can never close the tag
 * (the Next.js JSON-LD guide's recommendation). */
export function jsonLdScript(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c")
}

function isHttpUrl(value: string | null | undefined): value is string {
  return !!value && /^https?:\/\//i.test(value)
}

interface PageMetaInput {
  title: string
  description: string
  path: string
  image?: string | null
  type?: "website" | "article"
  publishedTime?: string | null
  modifiedTime?: string | null
}

/** Title, description, canonical, Open Graph and Twitter card for a public page. */
export function pageMetadata(input: PageMetaInput): Metadata {
  const url = absoluteUrl(input.path)
  const image = isHttpUrl(input.image) ? input.image : undefined
  const description = truncate(input.description, 200)
  return {
    title: input.title,
    description,
    alternates: { canonical: url },
    openGraph: {
      title: input.title,
      description,
      url,
      siteName: SITE_NAME,
      type: input.type ?? "website",
      ...(input.type === "article" && input.publishedTime ? { publishedTime: input.publishedTime } : {}),
      ...(input.type === "article" && input.modifiedTime ? { modifiedTime: input.modifiedTime } : {}),
      ...(image ? { images: [{ url: image }] } : {}),
    },
    twitter: {
      card: image ? "summary_large_image" : "summary",
      title: input.title,
      description,
      ...(image ? { images: [image] } : {}),
    },
  }
}

// -- per-page metadata ----------------------------------------------------------------

export function articleMetadata(article: ArticleDetail): Metadata {
  return pageMetadata({
    title: article.title,
    description: article.excerpt || truncate(article.content_text, 200),
    path: `/article/${article.slug}`,
    image: article.featured_image_url,
    type: "article",
    publishedTime: article.published_at,
    modifiedTime: article.updated_at,
  })
}

export function teamMetadata(team: TeamDetail): Metadata {
  return pageMetadata({
    title: `${team.name} — fixtures, results, squad & news`,
    description: `${team.name}${team.country ? ` (${team.country})` : ""}: upcoming fixtures, latest results, form, squad and football news on ${SITE_NAME}.`,
    path: `/team/${team.id}`,
    image: team.logo_url,
  })
}

export function competitionMetadata(competition: CompetitionOut): Metadata {
  return pageMetadata({
    title: `${competition.name} — table, fixtures, results & news`,
    description: `${competition.name}${competition.country ? ` (${competition.country})` : ""}: standings, fixtures, results, top scorers and the latest news on ${SITE_NAME}.`,
    path: `/competition/${competition.id}`,
    image: competition.logo_url,
  })
}

export function playerMetadata(player: PlayerDetail): Metadata {
  const facts = [player.position, player.nationality, player.team?.name].filter(Boolean).join(", ")
  return pageMetadata({
    title: `${player.name} — stats & news`,
    description: `${player.name}${facts ? ` (${facts})` : ""}: season statistics, recent matches and news on ${SITE_NAME}.`,
    path: `/player/${player.id}`,
    image: player.photo_url,
  })
}

export function matchTitle(match: MatchSummary): string {
  return `${match.home_team.name} vs ${match.away_team.name}`
}

export function matchMetadata(match: MatchDetail): Metadata {
  const state =
    match.status === "finished"
      ? `Full-time: ${match.home_team.name} ${match.home_score}-${match.away_score} ${match.away_team.name}.`
      : match.status === "live" || match.status === "halftime"
        ? `Follow ${match.home_team.name} vs ${match.away_team.name} live.`
        : `${match.home_team.name} vs ${match.away_team.name} kicks off ${match.kickoff_time.slice(0, 10)}.`
  return pageMetadata({
    title: `${matchTitle(match)} — ${match.competition.name}`,
    description: `${state} Timeline, line-ups, statistics and news on ${SITE_NAME}.`,
    path: `/match/${match.id}`,
    image: match.home_team.logo_url,
  })
}

// -- structured data (schema.org) ----------------------------------------------------------
// Only facts the page really shows: a missing field is omitted, never invented.

export function articleJsonLd(article: ArticleDetail) {
  const url = absoluteUrl(`/article/${article.slug}`)
  return {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    mainEntityOfPage: { "@type": "WebPage", "@id": url },
    headline: truncate(article.title, 110),
    description: article.excerpt || undefined,
    url,
    datePublished: article.published_at ?? undefined,
    dateModified: article.updated_at,
    image: isHttpUrl(article.featured_image_url) ? [article.featured_image_url] : undefined,
    author: article.author_name ? { "@type": "Person", name: article.author_name } : undefined,
    publisher: { "@type": "Organization", name: SITE_NAME, url: SITE_URL },
    articleSection: article.category?.name,
    keywords: article.tags.length ? article.tags.map((t) => t.name).join(", ") : undefined,
    about: article.teams.length
      ? article.teams.map((t) => ({ "@type": "SportsTeam", name: t.name, url: absoluteUrl(`/team/${t.id}`) }))
      : undefined,
  }
}

export function teamJsonLd(team: TeamDetail) {
  return {
    "@context": "https://schema.org",
    "@type": "SportsTeam",
    name: team.name,
    sport: "Football",
    url: absoluteUrl(`/team/${team.id}`),
    logo: isHttpUrl(team.logo_url) ? team.logo_url : undefined,
  }
}

export function competitionJsonLd(competition: CompetitionOut) {
  return {
    "@context": "https://schema.org",
    "@type": "SportsOrganization",
    name: competition.name,
    sport: "Football",
    url: absoluteUrl(`/competition/${competition.id}`),
    logo: isHttpUrl(competition.logo_url) ? competition.logo_url : undefined,
  }
}

export function playerJsonLd(player: PlayerDetail) {
  return {
    "@context": "https://schema.org",
    "@type": "Person",
    name: player.name,
    url: absoluteUrl(`/player/${player.id}`),
    image: isHttpUrl(player.photo_url) ? player.photo_url : undefined,
    nationality: player.nationality ? { "@type": "Country", name: player.nationality } : undefined,
    affiliation: player.team
      ? { "@type": "SportsTeam", name: player.team.name, url: absoluteUrl(`/team/${player.team.id}`) }
      : undefined,
  }
}

const EVENT_STATUS: Record<string, string> = {
  postponed: "https://schema.org/EventPostponed",
  cancelled: "https://schema.org/EventCancelled",
}

export function matchJsonLd(match: MatchDetail) {
  const team = (t: MatchSummary["home_team"]) => ({
    "@type": "SportsTeam",
    name: t.name,
    sport: "Football",
    url: absoluteUrl(`/team/${t.id}`),
  })
  return {
    "@context": "https://schema.org",
    "@type": "SportsEvent",
    name: matchTitle(match),
    sport: "Football",
    url: absoluteUrl(`/match/${match.id}`),
    startDate: match.kickoff_time,
    // schema.org has no "live"/"finished" status; those events were scheduled.
    eventStatus: EVENT_STATUS[match.status] ?? "https://schema.org/EventScheduled",
    homeTeam: team(match.home_team),
    awayTeam: team(match.away_team),
    location: match.venue ? { "@type": "Place", name: match.venue } : undefined,
  }
}
