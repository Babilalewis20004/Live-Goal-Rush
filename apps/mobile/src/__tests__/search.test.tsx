import { fireEvent, render, screen, waitFor } from "@testing-library/react-native"
import { router } from "expo-router"

import SearchScreen from "@/app/(tabs)/search"
import { api } from "@/lib/api"
import type { SearchResults } from "@/types/api"

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
      getSearchSuggestions: jest.fn(),
      getPopularSearches: jest.fn(),
      search: jest.fn(),
      trackSearch: jest.fn(),
    },
  }
})

const mockRecent = { recent: [] as string[], remember: jest.fn(), forget: jest.fn(), forgetAll: jest.fn() }
jest.mock("@/hooks/use-recent-searches", () => ({ useRecentSearches: () => mockRecent }))

const mockApi = api as unknown as Record<"getSearchSuggestions" | "getPopularSearches" | "search" | "trackSearch", jest.Mock>

const ARSENAL = { id: 5, name: "Arsenal", short_name: "ARS", country: null, logo_url: null }
const RESULTS: SearchResults = {
  teams: [ARSENAL],
  competitions: [],
  players: [{ id: 9, name: "Bukayo Saka", position: "Forward", photo_url: null }],
  matches: [],
  articles: [
    {
      id: 1,
      slug: "arsenal-win",
      title: "Arsenal win again",
      excerpt: "",
      featured_image_url: null,
      featured_image_alt: null,
      published_at: null,
      category: null,
      author_name: null,
      tags: [],
      relation: null,
      reason: null,
    },
  ],
}

beforeEach(() => {
  for (const fn of Object.values(mockApi)) fn.mockReset()
  mockApi.getPopularSearches.mockResolvedValue({ queries: [] })
  mockApi.trackSearch.mockResolvedValue(undefined)
  mockApi.getSearchSuggestions.mockResolvedValue({ query: "", suggestions: [] })
  mockRecent.recent = []
  mockRecent.remember.mockReset()
  ;(router.push as jest.Mock).mockReset()
})

const search = () => screen.getByLabelText(/Search teams, players, competitions, matches and news/)

describe("unified search", () => {
  it("starts with recent and popular searches and an empty-state hint", async () => {
    mockRecent.recent = ["Liverpool"]
    mockApi.getPopularSearches.mockResolvedValue({ queries: ["champions league"] })
    await render(<SearchScreen />)
    expect(screen.getByText("Liverpool")).toBeTruthy()
    expect(await screen.findByRole("button", { name: "Search champions league" })).toBeTruthy()
    expect(screen.getByText("Search for teams, players, competitions, matches or news.")).toBeTruthy()
  })

  it("lets the user forget a recent search or clear them all", async () => {
    mockRecent.recent = ["Liverpool"]
    await render(<SearchScreen />)
    await fireEvent.press(screen.getByRole("button", { name: "Remove Liverpool from recent searches" }))
    expect(mockRecent.forget).toHaveBeenCalledWith("Liverpool")
    await fireEvent.press(screen.getByRole("button", { name: "Clear all recent searches" }))
    expect(mockRecent.forgetAll).toHaveBeenCalled()
  })

  it("suggests as you type and opens the chosen result, recording the choice", async () => {
    mockApi.getSearchSuggestions.mockResolvedValue({
      query: "ars",
      suggestions: [
        { type: "team", id: 5, label: "Arsenal", slug: null },
        { type: "article", id: 1, label: "Arsenal win again", slug: "arsenal-win" },
      ],
    })
    await render(<SearchScreen />)
    await fireEvent.changeText(search(), "ars")
    const team = await screen.findByRole("button", { name: "Team: Arsenal" })
    await fireEvent.press(team)
    expect(mockApi.trackSearch).toHaveBeenCalledWith("ars", "team", 5)
    expect(router.push).toHaveBeenCalledWith({ pathname: "/team/[id]", params: { id: "5" } })

    await fireEvent.press(screen.getByRole("button", { name: "News: Arsenal win again" }))
    expect(router.push).toHaveBeenLastCalledWith({ pathname: "/article/[slug]", params: { slug: "arsenal-win" } })
  })

  it("shows grouped results on submit, including news, and remembers the query", async () => {
    mockApi.search.mockResolvedValue(RESULTS)
    await render(<SearchScreen />)
    await fireEvent.changeText(search(), "Arsenal")
    await fireEvent(search(), "submitEditing")
    expect(await screen.findByText("Bukayo Saka")).toBeTruthy()
    expect(screen.getByRole("header", { name: "Teams" })).toBeTruthy()
    expect(screen.getByRole("header", { name: "Players" })).toBeTruthy()
    expect(screen.getByRole("header", { name: "News" })).toBeTruthy()
    expect(screen.getByText("Arsenal win again")).toBeTruthy()
    expect(mockApi.search).toHaveBeenCalledWith("Arsenal")
    expect(mockRecent.remember).toHaveBeenCalledWith("Arsenal")
  })

  it("explains an empty result, a rate limit and a failure", async () => {
    mockApi.search.mockResolvedValueOnce({ teams: [], competitions: [], players: [], matches: [], articles: [] })
    await render(<SearchScreen />)
    await fireEvent.changeText(search(), "zzzz")
    await fireEvent(search(), "submitEditing")
    expect(await screen.findByText(/No results for "zzzz"/)).toBeTruthy()

    const { ApiError } = jest.requireMock("@/lib/api")
    mockApi.search.mockRejectedValueOnce(new ApiError(429, "slow down"))
    await fireEvent.changeText(search(), "arsenal")
    await fireEvent(search(), "submitEditing")
    expect(await screen.findByText(/searching a little fast/)).toBeTruthy()

    mockApi.search.mockRejectedValueOnce(new Error("offline"))
    await fireEvent.changeText(search(), "chelsea")
    await fireEvent(search(), "submitEditing")
    expect(await screen.findByText("Unable to search right now.")).toBeTruthy()
  })

  it("clears everything with the clear button", async () => {
    mockApi.search.mockResolvedValue(RESULTS)
    await render(<SearchScreen />)
    await fireEvent.changeText(search(), "Arsenal")
    await fireEvent(search(), "submitEditing")
    await screen.findByText("Bukayo Saka")
    await fireEvent.press(screen.getByRole("button", { name: "Clear search" }))
    await waitFor(() => expect(screen.queryByText("Bukayo Saka")).toBeNull())
    expect(search().props.value).toBe("")
  })

  it("does not search for blank input and caps the length", async () => {
    await render(<SearchScreen />)
    await fireEvent.changeText(search(), "   ")
    await fireEvent(search(), "submitEditing")
    expect(mockApi.search).not.toHaveBeenCalled()
    await fireEvent.changeText(search(), "x".repeat(150))
    expect(search().props.value).toHaveLength(100)
  })
})
