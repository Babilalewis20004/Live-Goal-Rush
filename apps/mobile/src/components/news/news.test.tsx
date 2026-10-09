import { fireEvent, render, screen, waitFor } from "@testing-library/react-native"

import { ContentNotificationSettings } from "@/components/content-notification-settings"
import { ArticleCard } from "@/components/news/article-card"
import { EntityNews } from "@/components/news/entity-news"
import { api } from "@/lib/api"
import type { ArticleSummary, Page } from "@/types/api"

jest.mock("@/lib/api", () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    ApiError,
    api: {
      getTeamNews: jest.fn(),
      getContentPreferences: jest.fn(),
      setContentPreference: jest.fn(),
    },
  }
})

const mockApi = api as unknown as Record<"getTeamNews" | "getContentPreferences" | "setContentPreference", jest.Mock>

const article = (id: number, overrides: Partial<ArticleSummary> = {}): ArticleSummary => ({
  id,
  slug: `story-${id}`,
  title: `Story ${id}`,
  excerpt: `Excerpt ${id}`,
  featured_image_url: null,
  featured_image_alt: null,
  published_at: "2026-10-02T10:00:00Z",
  category: { id: 1, slug: "transfers", name: "Transfers", competition_id: null },
  author_name: "Sam Writer",
  tags: [],
  relation: null,
  reason: null,
  ...overrides,
})

const page = (items: ArticleSummary[], total: number, pageNo = 1): Page<ArticleSummary> => ({
  items,
  total,
  page: pageNo,
  page_size: 10,
})

beforeEach(() => {
  for (const fn of Object.values(mockApi)) fn.mockReset()
})

describe("ArticleCard", () => {
  it("is one accessible link carrying headline, relation and date, and links to the article", async () => {
    await render(<ArticleCard article={article(1, { relation: "match" })} />)
    const card = screen.getByRole("link", { name: /Story 1\. About this match, Transfers · 2 Oct 2026/ })
    expect(JSON.parse(card.props.testHref)).toEqual({ pathname: "/article/[slug]", params: { slug: "story-1" } })
    expect(screen.getByText("Excerpt 1")).toBeTruthy()
    expect(screen.getByText("About this match")).toBeTruthy() // state is words, not only colour
    expect(screen.getByText(/By Sam Writer/)).toBeTruthy()
  })

  it("shows why a related article was suggested", async () => {
    await render(<ArticleCard article={article(2, { reason: "Same competition, same team" })} />)
    expect(screen.getByText("Suggested: same competition, same team")).toBeTruthy()
  })

  it("compact cards leave out the excerpt and image", async () => {
    await render(<ArticleCard compact article={article(3, { featured_image_url: "https://cdn.example/a.jpg" })} />)
    expect(screen.queryByText("Excerpt 3")).toBeNull()
    expect(screen.getByText("Story 3")).toBeTruthy()
  })
})

describe("EntityNews", () => {
  it("says so when there is nothing linked, rather than padding with other stories", async () => {
    await render(<EntityNews kind="team" id={5} initial={page([], 0)} />)
    expect(screen.getByText("No news linked to this yet.")).toBeTruthy()
  })

  it("loads further pages on demand without duplicating items", async () => {
    mockApi.getTeamNews.mockResolvedValue(page([article(2), article(1), article(3)], 3, 2))
    await render(<EntityNews kind="team" id={5} initial={page([article(1), article(2)], 3)} />)
    await fireEvent.press(screen.getByRole("button", { name: /Load 1 more articles/ }))
    await waitFor(() => expect(screen.getByText("Story 3")).toBeTruthy())
    expect(mockApi.getTeamNews).toHaveBeenCalledWith(5, 2)
    expect(screen.getAllByText("Story 1")).toHaveLength(1)
    expect(screen.queryByRole("button", { name: /Load/ })).toBeNull() // everything is loaded
  })

  it("reports a failed page load and lets the user retry", async () => {
    mockApi.getTeamNews.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(page([article(2)], 2, 2))
    await render(<EntityNews kind="team" id={5} initial={page([article(1)], 2)} />)
    await fireEvent.press(screen.getByRole("button", { name: /Load 1 more/ }))
    expect(await screen.findByRole("alert")).toBeTruthy()
    await fireEvent.press(screen.getByRole("button", { name: /Load 1 more/ }))
    await waitFor(() => expect(screen.getByText("Story 2")).toBeTruthy())
  })
})

describe("ContentNotificationSettings", () => {
  const prefs = (overrides: Record<string, boolean> = {}) =>
    ["team_news", "competition_news", "match_reports", "transfer_news", "general_news"].map((kind) => ({
      kind,
      enabled: overrides[kind] ?? false,
      default: false,
    }))

  it("lists every kind, all off by default, and saves a switch", async () => {
    mockApi.getContentPreferences.mockResolvedValue(prefs())
    mockApi.setContentPreference.mockResolvedValue({ kind: "team_news", enabled: true, default: false })
    await render(<ContentNotificationSettings />)
    const teamNews = await screen.findByLabelText("Team news")
    expect(teamNews.props.value).toBe(false)
    expect(screen.getByLabelText("General football news").props.value).toBe(false)

    await fireEvent(teamNews, "valueChange", true)
    await waitFor(() => expect(mockApi.setContentPreference).toHaveBeenCalledWith("team_news", true))
    expect(screen.getByLabelText("Team news").props.value).toBe(true)
  })

  it("puts the switch back and says so when saving fails", async () => {
    mockApi.getContentPreferences.mockResolvedValue(prefs({ team_news: true }))
    mockApi.setContentPreference.mockRejectedValue(new Error("nope"))
    await render(<ContentNotificationSettings />)
    const teamNews = await screen.findByLabelText("Team news")
    expect(teamNews.props.value).toBe(true)
    await fireEvent(teamNews, "valueChange", false)
    expect(await screen.findByRole("alert")).toBeTruthy()
    expect(screen.getByLabelText("Team news").props.value).toBe(true)
  })

  it("renders nothing at all if the preferences cannot be loaded", async () => {
    mockApi.getContentPreferences.mockRejectedValue(new Error("offline"))
    await render(<ContentNotificationSettings />)
    await waitFor(() => expect(mockApi.getContentPreferences).toHaveBeenCalled())
    expect(screen.queryByText("News notifications")).toBeNull()
  })
})
