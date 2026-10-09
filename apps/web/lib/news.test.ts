import { describe, expect, it } from "vitest"

import { CONTENT_KINDS, formatArticleDate, newsHref, relationLabel, trendLabel } from "@/lib/news"

describe("news helpers", () => {
  it("formats dates in UTC and tolerates missing or bad ones", () => {
    expect(formatArticleDate("2026-10-02T23:30:00Z")).toBe("2 Oct 2026")
    expect(formatArticleDate(null)).toBe("")
    expect(formatArticleDate("not a date")).toBe("")
  })

  it("explains trending in words, from the signals that really applied", () => {
    expect(trendLabel({ live_matches: 1, views: 4 })).toBe("Playing live now")
    expect(trendLabel({ views: 4 })).toBe("Popular in the last 24 hours")
    expect(trendLabel({ searches: 1 })).toBe("Popular in the last 24 hours")
    expect(trendLabel({ news: 2 })).toBe("In the news")
    expect(trendLabel({ follows: 3 })).toBe("Gaining followers")
    expect(trendLabel({})).toBe("Trending")
  })

  it("labels how a news item relates to a match page", () => {
    expect(relationLabel("match")).toBe("About this match")
    expect(relationLabel("team")).toBe("Team news")
    expect(relationLabel("competition")).toBe("Competition news")
    expect(relationLabel(null)).toBeNull()
  })

  it("gives each filter state exactly one URL", () => {
    expect(newsHref({})).toBe("/news")
    expect(newsHref({ page: 1 })).toBe("/news")
    expect(newsHref({ category: "transfers", page: 3 })).toBe("/news?category=transfers&page=3")
    expect(newsHref({ tag: "real-madrid" })).toBe("/news?tag=real-madrid")
  })

  it("lists every notification kind the API knows", () => {
    expect(CONTENT_KINDS.map((k) => k.kind).sort()).toEqual(
      ["comment_replies", "competition_news", "editorial_updates", "general_news", "match_reports", "poll_closing", "poll_results", "prediction_available", "subscription_events", "team_insights", "team_news", "transfer_news"].sort(),
    )
  })
})
