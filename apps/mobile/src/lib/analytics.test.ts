
import {
  comparisonShares,
  confidenceText,
  coverage,
  ENTITLEMENT,
  formatNumber,
  formatPrice,
  formatStat,
  hasEntitlement,
  leader,
  outcomePercentages,
  rowSummary,
  subscriptionStatusText,
  timeAgo,
} from "./analytics"
import type { ComparisonRow } from "@/types/api"

const row = (over: Partial<ComparisonRow> = {}): ComparisonRow => ({
  key: "k", label: "Shots", home: 12, away: 8, higher_is_better: true, home_sample: 5, away_sample: 5, premium: true, ...over,
})

describe("formatting never turns missing data into zero", () => {
  it("shows a dash for null and keeps genuine zeros", () => {
    expect(formatStat({ value: null, sample: 0 })).toBe("—")
    expect(formatStat(undefined)).toBe("—")
    expect(formatStat({ value: 0, sample: 4 })).toBe("0")
    expect(formatStat({ value: 12.5, sample: 4 }, { suffix: "%" })).toBe("12.5%")
    expect(formatStat({ value: 12, sample: 4 })).toBe("12")
    expect(formatStat({ value: 1.234, sample: 4 }, { digits: 2 })).toBe("1.23")
    expect(formatNumber(null)).toBe("—")
    expect(formatNumber(2.5)).toBe("2.5")
  })

  it("reports partial coverage honestly", () => {
    expect(coverage({ value: 4, sample: 4 }, 10)).toBe("4 of 10 matches")
    expect(coverage({ value: 4, sample: 10 }, 10)).toBeNull()
    expect(coverage({ value: null, sample: 0 }, 10)).toBeNull()
  })
})

describe("outcome percentages", () => {
  const names = { home: "Reds", away: "Blues" }

  it("always sum to exactly 100", () => {
    for (const [h, d, a] of [[0.4849, 0.2651, 0.25], [1 / 3, 1 / 3, 1 / 3], [0.7004, 0.1498, 0.1498], [0.999, 0.0005, 0.0005]]) {
      const out = outcomePercentages({ home_win: h, draw: d, away_win: a }, names)!
      expect(out.reduce((s, o) => s + o.percent, 0)).toBe(100)
    }
  })

  it("labels the three outcomes in order and refuses to invent missing probabilities", () => {
    const out = outcomePercentages({ home_win: 0.48, draw: 0.27, away_win: 0.25 }, names)!
    expect(out.map((o) => [o.key, o.label, o.percent])).toEqual([["home", "Reds", 48], ["draw", "Draw", 27], ["away", "Blues", 25]])
    expect(outcomePercentages({ home_win: null, draw: null, away_win: null }, names)).toBeNull()
  })

  it("describes confidence without implying accuracy", () => {
    expect(confidenceText("low")).toMatch(/little history/)
    expect(confidenceText(null)).toBeNull()
    for (const level of ["low", "medium", "high"] as const) expect(confidenceText(level)).not.toMatch(/accura|guarantee|certain/i)
  })
})

describe("comparison rows", () => {
  const names = { home: "Reds", away: "Blues" }

  it("computes bar shares and skips them when a side has no data", () => {
    expect(comparisonShares(row())).toEqual({ home: 60, away: 40 })
    expect(comparisonShares(row({ home: 0, away: 0 }))).toEqual({ home: 50, away: 50 })
    expect(comparisonShares(row({ away: null }))).toBeNull()
  })

  it("decides who leads, respecting 'lower is better' and neutral stats", () => {
    expect(leader(row())).toBe("home")
    expect(leader(row({ home: 3, away: 9, higher_is_better: false }))).toBe("home") // conceded fewer
    expect(leader(row({ home: 9, away: 3, higher_is_better: false }))).toBe("away")
    expect(leader(row({ home: 5, away: 5 }))).toBe("level")
    expect(leader(row({ higher_is_better: null }))).toBeNull() // possession: style, not quality
    expect(leader(row({ home: null }))).toBeNull()
  })

  it("has a text summary so colour and bars are never the only signal", () => {
    expect(rowSummary(row(), names)).toBe("Shots: Reds 12, Blues 8; Reds ahead")
    expect(rowSummary(row({ away: null, higher_is_better: null }), names)).toBe("Shots: Reds 12, Blues —")
  })
})

describe("premium helpers", () => {
  it("checks entitlements by key", () => {
    expect(hasEntitlement(["advanced_analytics"], ENTITLEMENT.advancedAnalytics)).toBe(true)
    expect(hasEntitlement([], ENTITLEMENT.advancedAnalytics)).toBe(false)
    expect(hasEntitlement(undefined, ENTITLEMENT.adFree)).toBe(false)
  })

  it("formats prices from minor units", () => {
    expect(formatPrice({ price_minor: 499, currency: "GBP", interval: "month" })).toBe("£4.99 / month")
    expect(formatPrice({ price_minor: 3999, currency: "GBP", interval: "year" })).toBe("£39.99 / year")
  })

  it("describes the subscription state in plain words", () => {
    expect(subscriptionStatusText("active", false, "2026-11-01T00:00:00Z")).toBe("Premium is active. Renews on 1 Nov 2026.")
    expect(subscriptionStatusText("cancelled", true, "2026-11-01T00:00:00Z")).toBe("Cancelled. You keep Premium until 1 Nov 2026.")
    expect(subscriptionStatusText("past_due", false, null)).toMatch(/payment method/)
    expect(subscriptionStatusText("none", false, null)).toBe("You're on the free plan.")
  })

  it("says how old generated data is", () => {
    const now = new Date("2026-10-08T12:00:00Z")
    expect(timeAgo("2026-10-08T11:59:30Z", now)).toBe("just now")
    expect(timeAgo("2026-10-08T11:30:00Z", now)).toBe("30 min ago")
    expect(timeAgo("2026-10-08T06:00:00Z", now)).toBe("6 h ago")
    expect(timeAgo(null, now)).toBeNull()
  })
})
