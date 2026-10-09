import { CONTENT_KINDS, formatArticleDate, relationLabel, trendLabel } from "@/lib/news"
import { MAX_RECENT, normalizeSearch, parseRecent, withRecent, withoutRecent } from "@/lib/search-history"
import { publicUrl } from "@/lib/site"

describe("news helpers", () => {
  it("formats dates in UTC and tolerates missing or bad ones", () => {
    expect(formatArticleDate("2026-10-02T23:30:00Z")).toBe("2 Oct 2026")
    expect(formatArticleDate(null)).toBe("")
    expect(formatArticleDate("nonsense")).toBe("")
  })

  it("explains trending in words from the signals that applied, never as a quality claim", () => {
    expect(trendLabel({ live_matches: 1, views: 4 })).toBe("Playing live now")
    expect(trendLabel({ views: 4 })).toBe("Popular in the last 24 hours")
    expect(trendLabel({ news: 2 })).toBe("In the news")
    expect(trendLabel({ follows: 3 })).toBe("Gaining followers")
    expect(trendLabel({})).toBe("Trending")
  })

  it("labels how a story relates to a match", () => {
    expect(relationLabel("match")).toBe("About this match")
    expect(relationLabel("team")).toBe("Team news")
    expect(relationLabel("competition")).toBe("Competition news")
    expect(relationLabel(null)).toBeNull()
  })

  it("offers every notification kind the API knows", () => {
    expect(CONTENT_KINDS.map((k) => k.kind).sort()).toEqual(
      ["comment_replies", "competition_news", "editorial_updates", "general_news", "match_reports", "poll_closing", "poll_results", "prediction_available", "subscription_events", "team_insights", "team_news", "transfer_news"].sort(),
    )
  })
})

describe("recent searches (on-device, signed-out)", () => {
  it("keeps newest first, case-insensitively unique and capped", () => {
    let list: string[] = []
    list = withRecent(list, "arsenal")
    list = withRecent(list, "chelsea")
    list = withRecent(list, "ARSENAL")
    expect(list).toEqual(["ARSENAL", "chelsea"])
    for (let i = 0; i < MAX_RECENT + 4; i++) list = withRecent(list, `query ${i}`)
    expect(list).toHaveLength(MAX_RECENT)
  })

  it("ignores one-character queries and removes by text", () => {
    expect(withRecent(["a b"], "x")).toEqual(["a b"])
    expect(withoutRecent(["One", "two"], "ONE")).toEqual(["two"])
  })

  it("normalises and survives corrupted storage", () => {
    expect(normalizeSearch("  man   utd ")).toBe("man utd")
    expect(normalizeSearch("x".repeat(200))).toHaveLength(100)
    expect(parseRecent(null)).toEqual([])
    expect(parseRecent("{oops")).toEqual([])
    expect(parseRecent(JSON.stringify([1, "ok", null]))).toEqual(["ok"])
    expect(parseRecent(JSON.stringify({ a: 1 }))).toEqual([])
  })
})

describe("share links", () => {
  it("are the canonical public URL of the thing, built from its id/slug alone", () => {
    expect(publicUrl("article", "some-slug")).toMatch(/\/article\/some-slug$/)
    expect(publicUrl("match", 12)).toMatch(/\/match\/12$/)
    expect(publicUrl("article", "weird slug/../x")).toMatch(/\/article\/weird%20slug%2F..%2Fx$/)
  })
})
