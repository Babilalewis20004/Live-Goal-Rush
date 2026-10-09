import { STALE_AFTER_MS, describeFreshness } from "./freshness"

const NOW = Date.parse("2026-10-08T15:00:00Z")
const ago = (ms: number) => NOW - ms

describe("describeFreshness", () => {
  it("trusts scores while the live connection is open", () => {
    expect(describeFreshness({ connection: "open", lastUpdatedAt: ago(10 * 60_000), now: NOW })).toEqual({ stale: false, message: null })
  })

  it("tolerates a brief reconnect without alarming anyone", () => {
    const result = describeFreshness({ connection: "reconnecting", lastUpdatedAt: ago(STALE_AFTER_MS - 1_000), now: NOW })
    expect(result.stale).toBe(false)
  })

  it("says the scores may be old once the connection has been down for a while", () => {
    const result = describeFreshness({ connection: "reconnecting", lastUpdatedAt: ago(3 * 60_000), now: NOW })
    expect(result.stale).toBe(true)
    expect(result.message).toMatch(/Reconnecting.*last updated .*3 min ago/)
  })

  it("says offline when the connection is closed", () => {
    const result = describeFreshness({ connection: "closed", lastUpdatedAt: ago(2 * 60_000), now: NOW })
    expect(result.stale).toBe(true)
    expect(result.message).toMatch(/offline.*2 min ago/i)
  })

  it("never shows a saved copy as current, however fresh the socket looks", () => {
    const result = describeFreshness({ connection: "open", lastUpdatedAt: ago(5 * 3_600_000), now: NOW, fromSavedCopy: true })
    expect(result.stale).toBe(true)
    expect(result.message).toMatch(/saved at .*5 h ago/)
  })

  it("marks scores stale when the last refresh failed even though a socket is open", () => {
    const result = describeFreshness({ connection: "open", lastUpdatedAt: ago(90_000), now: NOW, lastRefreshFailed: true })
    expect(result.stale).toBe(true)
  })

  it("is honest when nothing has ever loaded", () => {
    expect(describeFreshness({ connection: "closed", lastUpdatedAt: null, now: NOW })).toEqual({
      stale: true,
      message: "Scores are unavailable right now.",
    })
  })

  it("words very old copies as over a day", () => {
    const result = describeFreshness({ connection: "closed", lastUpdatedAt: ago(30 * 3_600_000), now: NOW, fromSavedCopy: true })
    expect(result.message).toMatch(/over a day ago/)
  })
})
