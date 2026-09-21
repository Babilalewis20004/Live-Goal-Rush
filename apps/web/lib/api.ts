import type {
  CompetitionOut,
  MatchDetail,
  MatchSummary,
  Page,
  SearchResults,
  StandingEntry,
  TeamOut,
} from "@/types/api"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = "ApiError"
  }
}

async function apiFetch<T>(path: string): Promise<T> {
  let res: Response
  try {
    // Live scores must never be served stale from Next.js's fetch cache;
    // Phase 2's caching layer (Redis, revalidateTag) replaces this.
    res = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" })
  } catch {
    throw new ApiError(0, "Unable to reach the football data service. Please try again.")
  }

  if (!res.ok) {
    if (res.status === 404) {
      throw new ApiError(404, "Not found")
    }
    throw new ApiError(res.status, "The football data service returned an error. Please try again.")
  }

  return (await res.json()) as T
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ""
}

export const api = {
  getLiveMatches: () => apiFetch<MatchSummary[]>("/api/v1/matches/live"),
  getTodayMatches: () => apiFetch<MatchSummary[]>("/api/v1/matches/today"),
  getUpcomingMatches: () => apiFetch<MatchSummary[]>("/api/v1/matches/upcoming"),
  getMatch: (id: number) => apiFetch<MatchDetail>(`/api/v1/matches/${id}`),
  getMatchEvents: (id: number) => apiFetch<MatchDetail["events"]>(`/api/v1/matches/${id}/events`),

  getCompetitions: (page = 1, pageSize = 50) =>
    apiFetch<Page<CompetitionOut>>(`/api/v1/competitions${query({ page, page_size: pageSize })}`),
  getCompetition: (id: number) => apiFetch<CompetitionOut>(`/api/v1/competitions/${id}`),
  getCompetitionFixtures: (id: number, page = 1, pageSize = 50) =>
    apiFetch<Page<MatchSummary>>(
      `/api/v1/competitions/${id}/fixtures${query({ page, page_size: pageSize })}`,
    ),
  getStandings: (id: number) => apiFetch<StandingEntry[]>(`/api/v1/competitions/${id}/standings`),

  getTeam: (id: number) => apiFetch<TeamOut>(`/api/v1/teams/${id}`),
  getTeamFixtures: (id: number, page = 1, pageSize = 50) =>
    apiFetch<Page<MatchSummary>>(`/api/v1/teams/${id}/fixtures${query({ page, page_size: pageSize })}`),
  getTeamResults: (id: number, page = 1, pageSize = 50) =>
    apiFetch<Page<MatchSummary>>(`/api/v1/teams/${id}/results${query({ page, page_size: pageSize })}`),

  search: (q: string) => apiFetch<SearchResults>(`/api/v1/search${query({ q })}`),
}
