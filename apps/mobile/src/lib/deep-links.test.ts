import { hrefForNotification, hrefForUrl } from "@/lib/deep-links"

describe("notification deep links", () => {
  it("opens each supported screen from the shared {type, id} payload", () => {
    expect(hrefForNotification({ type: "match", id: 42 })).toBe("/match/42")
    expect(hrefForNotification({ type: "team", id: "7" })).toBe("/team/7")
    expect(hrefForNotification({ type: "competition", id: 2 })).toBe("/competition/2")
    expect(hrefForNotification({ type: "player", id: 9 })).toBe("/player/9")
    // for an article the id is its slug
    expect(hrefForNotification({ type: "article", id: "arsenal-edge-a-thriller" })).toBe("/article/arsenal-edge-a-thriller")
    expect(hrefForNotification({ type: "poll", id: 12 })).toBe("/poll/12")
    expect(hrefForNotification({ type: "premium", id: 0 })).toBe("/premium")
    expect(hrefForNotification({ type: "premium" })).toBe("/premium")
    expect(hrefForNotification({ type: "editor", id: 7 })).toBe("/editor/7")
  })

  it("refuses anything that is not a known screen or a plain id", () => {
    expect(hrefForNotification(null)).toBeNull()
    expect(hrefForNotification({})).toBeNull()
    expect(hrefForNotification({ type: "login", id: 1 })).toBeNull()
    expect(hrefForNotification({ type: "../admin", id: 1 })).toBeNull()
    expect(hrefForNotification({ type: "article", id: "../../notification-settings" })).toBeNull()
    expect(hrefForNotification({ type: "article", id: "a/b" })).toBeNull()
    expect(hrefForNotification({ type: "article", id: "" })).toBeNull()
    expect(hrefForNotification({ type: "article", id: { a: 1 } })).toBeNull()
    expect(hrefForNotification({ type: 5, id: 1 })).toBeNull()
  })
})

describe("links opened from outside the app", () => {
  it("maps public web URLs and plural aliases to app screens", () => {
    expect(hrefForUrl("https://livepitch.example/article/some-slug")).toBe("/article/some-slug")
    expect(hrefForUrl("https://livepitch.example/matches/12?utm=x#frag")).toBe("/match/12")
    expect(hrefForUrl("https://livepitch.example/teams/3")).toBe("/team/3")
    expect(hrefForUrl("https://livepitch.example/players/4")).toBe("/player/4")
    expect(hrefForUrl("https://livepitch.example/competitions/5")).toBe("/competition/5")
  })

  it("understands bare paths and custom-scheme links", () => {
    expect(hrefForUrl("/matches/12")).toBe("/match/12")
    expect(hrefForUrl("/article/some-slug")).toBe("/article/some-slug")
    expect(hrefForUrl("mobile://teams/3")).toBe("/team/3")
    expect(hrefForUrl("mobile://article/some-slug")).toBe("/article/some-slug")
  })

  it("ignores everything else", () => {
    expect(hrefForUrl("https://livepitch.example/")).toBeNull()
    expect(hrefForUrl("https://livepitch.example/profile/1")).toBeNull()
    expect(hrefForUrl("https://livepitch.example/article/%E0%A4%A")).toBeNull()
    expect(hrefForUrl("not a url")).toBeNull()
    expect(hrefForUrl("/login")).toBeNull()
    expect(hrefForUrl("/matches")).toBeNull()
    expect(hrefForUrl("/article/../notification-settings")).toBeNull()
  })
})
