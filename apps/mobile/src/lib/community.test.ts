import {
  COMMENT_MAX_LENGTH,
  EMPTY_REACTIONS,
  applyReaction,
  countLinks,
  leadingOption,
  pollClosing,
  relativeTime,
  validateComment,
} from "@/lib/community"
import type { PollOut } from "@/types/api"

describe("comment validation", () => {
  it("accepts ordinary comments and refuses blanks, essays and link spam", () => {
    expect(validateComment("Brilliant goal!")).toBeNull()
    expect(validateComment("   ")).toMatch(/something/)
    expect(validateComment("x".repeat(COMMENT_MAX_LENGTH + 1))).toMatch(/limited/)
    expect(validateComment("x".repeat(COMMENT_MAX_LENGTH))).toBeNull()
    expect(validateComment("see https://a.example and www.b.example")).toBeNull()
    expect(validateComment("https://a.example https://b.example https://c.example")).toMatch(/at most 2 links/)
  })

  it("counts links case-insensitively", () => {
    expect(countLinks("HTTP://x.example Www.y.example plain text")).toBe(2)
    expect(countLinks("no links here")).toBe(0)
  })
})

describe("relativeTime", () => {
  const now = new Date("2026-10-08T12:00:00Z")
  it("speaks in the coarsest honest unit", () => {
    expect(relativeTime("2026-10-08T11:59:40Z", now)).toBe("just now")
    expect(relativeTime("2026-10-08T11:30:00Z", now)).toBe("30 min ago")
    expect(relativeTime("2026-10-08T07:00:00Z", now)).toBe("5 h ago")
    expect(relativeTime("2026-10-05T12:00:00Z", now)).toBe("3 d ago")
    expect(relativeTime("2026-09-01T12:00:00Z", now)).toMatch(/^1 Sept? 2026$/) // month spelling varies by ICU version
    expect(relativeTime("garbage", now)).toBe("")
    expect(relativeTime("2026-10-08T13:00:00Z", now)).toBe("just now") // clock skew never says "in the future"
  })
})

describe("reactions", () => {
  it("adds, switches and removes a reaction, keeping the total honest", () => {
    const first = applyReaction(EMPTY_REACTIONS, "fire")
    expect(first).toMatchObject({ mine: "fire", total: 1, counts: { fire: 1 } })
    const switched = applyReaction(first, "goal")
    expect(switched.counts).toMatchObject({ fire: 0, goal: 1 })
    expect(switched.mine).toBe("goal")
    const removed = applyReaction(switched, "goal")
    expect(removed).toMatchObject({ mine: null, total: 0 })
    expect(EMPTY_REACTIONS.total).toBe(0) // the input is never mutated
  })

  it("never goes below zero", () => {
    const odd = applyReaction({ counts: { thumbs_up: 0, fire: 0, wow: 0, goal: 0, heart: 0, laugh: 0, clap: 0 }, total: 0, mine: "wow" }, "fire")
    expect(odd.counts.wow).toBe(0)
  })
})

const poll = (overrides: Partial<PollOut> = {}): PollOut => ({
  id: 1,
  question: "Who wins?",
  kind: "question",
  status: "open",
  match_id: null,
  article_id: null,
  closes_at: null,
  total_votes: 3,
  options: [
    { id: 1, label: "Red", votes: 2, percent: 66.7 },
    { id: 2, label: "Blue", votes: 1, percent: 33.3 },
  ],
  my_vote: null,
  winner_option_id: null,
  ...overrides,
})

describe("poll helpers", () => {
  const now = new Date("2026-10-08T12:00:00Z")
  it("describes when a poll closes", () => {
    expect(pollClosing(poll(), now)).toBe("")
    expect(pollClosing(poll({ status: "closed" }), now)).toBe("Closed")
    expect(pollClosing(poll({ closes_at: "2026-10-08T12:30:00Z" }), now)).toBe("Closes in 30 min")
    expect(pollClosing(poll({ closes_at: "2026-10-08T17:00:00Z" }), now)).toBe("Closes in 5 h")
    expect(pollClosing(poll({ closes_at: "2026-10-12T12:00:00Z" }), now)).toBe("Closes in 4 d")
    expect(pollClosing(poll({ closes_at: "2026-10-08T11:00:00Z" }), now)).toBe("Closing now")
  })

  it("names the leader in words, and none on a tie or with no votes", () => {
    expect(leadingOption(poll())).toBe("Red")
    expect(leadingOption(poll({ total_votes: 0, options: poll().options.map((o) => ({ ...o, votes: 0 })) }))).toBeNull()
    expect(leadingOption(poll({ options: poll().options.map((o) => ({ ...o, votes: 1 })) }))).toBeNull()
  })
})
