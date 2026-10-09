import { describe, expect, it } from "vitest"

import {
  absoluteUrl,
  articleJsonLd,
  articleMetadata,
  competitionJsonLd,
  jsonLdScript,
  matchJsonLd,
  matchMetadata,
  playerJsonLd,
  teamJsonLd,
  teamMetadata,
  truncate,
} from "@/lib/seo"
import type { ArticleDetail, MatchDetail, PlayerDetail, TeamDetail } from "@/types/api"

const article: ArticleDetail = {
  id: 1,
  slug: "arsenal-edge-a-thriller",
  title: "Arsenal edge a thriller",
  excerpt: "A late goal settles it.",
  featured_image_url: "https://cdn.example/a.jpg",
  featured_image_alt: "Celebration",
  published_at: "2026-10-01T12:00:00Z",
  category: { id: 1, slug: "match-reports", name: "Match Reports", competition_id: null },
  author_name: "Sam Writer",
  tags: [{ id: 1, slug: "arsenal", name: "Arsenal" }],
  relation: null,
  reason: null,
  content: "<p>Body</p>",
  content_text: "Body",
  content_blocks: [{ type: "paragraph", text: "Body" }],
  updated_at: "2026-10-02T09:00:00Z",
  view_count: 3,
  canonical_path: "/article/arsenal-edge-a-thriller",
  teams: [{ id: 7, name: "Arsenal", short_name: "ARS", country: "England", logo_url: null }],
  players: [],
  competitions: [],
  matches: [],
  gallery: [],
}

const team: TeamDetail = {
  id: 7,
  name: "Arsenal",
  short_name: "ARS",
  country: "England",
  logo_url: "https://cdn.example/ars.png",
  venue: null,
  competitions: [],
}

describe("absoluteUrl", () => {
  it("maps a path to exactly one canonical URL (no query, fragment or trailing slash)", () => {
    const base = absoluteUrl("/team/7")
    expect(absoluteUrl("/team/7/")).toBe(base)
    expect(absoluteUrl("/team/7?tab=squad")).toBe(base)
    expect(absoluteUrl("/team/7#form")).toBe(base)
    expect(absoluteUrl("team/7")).toBe(base)
    expect(base.endsWith("/team/7")).toBe(true)
  })
})

describe("truncate", () => {
  it("collapses whitespace and cuts on a word boundary with an ellipsis", () => {
    expect(truncate("one   two\nthree", 50)).toBe("one two three")
    const cut = truncate("alpha beta gamma delta", 14)
    expect(cut.endsWith("…")).toBe(true)
    expect(cut.length).toBeLessThanOrEqual(14)
    expect(cut).toBe("alpha beta…")
  })
})

describe("jsonLdScript", () => {
  it("can never close the surrounding script tag", () => {
    const out = jsonLdScript({ headline: "</script><script>alert(1)</script>" })
    expect(out).not.toContain("<")
    expect(JSON.parse(out).headline).toBe("</script><script>alert(1)</script>")
  })
})

describe("article SEO", () => {
  it("has a canonical URL, Open Graph article fields and a large social image", () => {
    const m = articleMetadata(article)
    expect(m.title).toBe("Arsenal edge a thriller")
    expect(m.description).toBe("A late goal settles it.")
    expect(m.alternates?.canonical).toBe(absoluteUrl("/article/arsenal-edge-a-thriller"))
    expect(m.openGraph).toMatchObject({
      type: "article",
      publishedTime: "2026-10-01T12:00:00Z",
      modifiedTime: "2026-10-02T09:00:00Z",
    })
    expect(m.twitter).toMatchObject({ card: "summary_large_image" })
  })

  it("falls back to a plain card when there is no usable image", () => {
    const m = articleMetadata({ ...article, featured_image_url: "javascript:alert(1)" })
    expect(m.twitter).toMatchObject({ card: "summary" })
    expect(JSON.stringify(m)).not.toContain("javascript:")
  })

  it("describes a NewsArticle truthfully and omits what it does not know", () => {
    const ld = articleJsonLd(article)
    expect(ld["@type"]).toBe("NewsArticle")
    expect(ld.headline).toBe("Arsenal edge a thriller")
    expect(ld.author).toEqual({ "@type": "Person", name: "Sam Writer" })
    expect(ld.about).toEqual([{ "@type": "SportsTeam", name: "Arsenal", url: absoluteUrl("/team/7") }])
    const anonymous = articleJsonLd({ ...article, author_name: null, featured_image_url: null, tags: [], teams: [] })
    expect(anonymous.author).toBeUndefined()
    expect(anonymous.image).toBeUndefined()
    expect(anonymous.about).toBeUndefined()
    expect(anonymous.keywords).toBeUndefined()
  })
})

describe("entity SEO", () => {
  it("team: canonical /team/{id}, SportsTeam", () => {
    expect(teamMetadata(team).alternates?.canonical).toBe(absoluteUrl("/team/7"))
    expect(teamJsonLd(team)).toMatchObject({ "@type": "SportsTeam", name: "Arsenal", sport: "Football" })
  })

  it("competition: SportsOrganization", () => {
    expect(
      competitionJsonLd({ id: 2, name: "Premier League", country: "England", logo_url: null, type: "league" }),
    ).toMatchObject({
      "@type": "SportsOrganization",
      url: absoluteUrl("/competition/2"),
    })
  })

  it("player: Person with only the facts we hold", () => {
    const player: PlayerDetail = {
      id: 9,
      name: "Haaland",
      position: null,
      photo_url: null,
      nationality: "Norway",
      shirt_number: null,
      team: null,
    }
    const ld = playerJsonLd(player)
    expect(ld).toMatchObject({ "@type": "Person", name: "Haaland", nationality: { "@type": "Country", name: "Norway" } })
    expect(ld.affiliation).toBeUndefined()
  })

  it("match: SportsEvent never claims live or a result as an event status", () => {
    const competition = { id: 2, name: "Premier League", country: "England", logo_url: null, type: "league" }
    const home = { id: 7, name: "Arsenal", short_name: "ARS", country: null, logo_url: null }
    const away = { id: 8, name: "Chelsea", short_name: "CHE", country: null, logo_url: null }
    const base = {
      id: 5,
      competition,
      home_team: home,
      away_team: away,
      kickoff_time: "2026-10-04T15:00:00Z",
      status: "live" as const,
      home_score: 1,
      away_score: 0,
      half_time_home_score: null,
      half_time_away_score: null,
      minute: 30,
      venue: "Emirates",
      last_synced_at: null,
      data_status: "FRESH" as const,
      events: [],
    } satisfies MatchDetail
    expect(matchJsonLd(base)).toMatchObject({
      "@type": "SportsEvent",
      name: "Arsenal vs Chelsea",
      eventStatus: "https://schema.org/EventScheduled",
      location: { name: "Emirates" },
    })
    expect(matchJsonLd({ ...base, status: "postponed", venue: null })).toMatchObject({
      eventStatus: "https://schema.org/EventPostponed",
      location: undefined,
    })
    expect(matchMetadata(base).description).toContain("live")
    expect(matchMetadata({ ...base, status: "finished" }).description).toContain("Arsenal 1-0 Chelsea")
  })
})
