import { clearTokens, getStoredAccessToken, getStoredRefreshToken, storeTokens } from "@/lib/auth-storage"
import type {
  AuthResponse,
  Capabilities,
  CompetitionOut,
  CompetitionSeasonsOut,
  DeviceOut,
  DeviceRegisterInput,
  FavouritesOut,
  HeadToHeadOut,
  MatchDetail,
  MatchFormOut,
  MatchLineupsOut,
  MatchPlayerStatisticsOut,
  MatchStatisticsOut,
  MatchSummary,
  NotificationPreferenceOut,
  NotificationScope,
  Page,
  PlayerDetail,
  PlayerOut,
  PlayerStatisticsOut,
  RealtimeEventType,
  SearchResults,
  StandingEntry,
  TeamDetail,
  TeamFormOut,
  TeamStatisticsOut,
  TopScorersOut,
  UserOut,
} from "@/types/api"

// The mobile app never talks to the football provider directly -- only to
// this backend, which is the same FastAPI service the web app uses.
const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000"

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = "ApiError"
  }
}

interface ApiFetchOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE"
  body?: unknown
  /** Internal: set on the retried request after a 401-triggered refresh,
   * so a second failure gives up instead of refreshing forever. */
  _retried?: boolean
}

// Mobile has no cookie jar to rely on (Phase 3 §5) -- every request carries
// its access token explicitly, and identifies itself as mobile so the auth
// endpoints return raw tokens in the body instead of only setting cookies.
async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Client": "mobile" }
  if (options.body !== undefined) headers["Content-Type"] = "application/json"
  const accessToken = await getStoredAccessToken()
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`

  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    })
  } catch {
    throw new ApiError(0, "Unable to reach the football data service. Please try again.")
  }

  if (res.status === 401 && !options._retried && !path.startsWith("/api/v1/auth/")) {
    const refreshed = await tryRefresh()
    if (refreshed) return apiFetch<T>(path, { ...options, _retried: true })
  }

  if (!res.ok) {
    if (res.status === 404) throw new ApiError(404, "Not found")
    let message = "The football data service returned an error. Please try again."
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body?.detail === "string") message = body.detail
    } catch {
      // Body wasn't JSON (or was empty) -- keep the generic message.
    }
    throw new ApiError(res.status, message)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

// Coalesces concurrent 401s onto a single in-flight refresh instead of each
// one racing its own /auth/refresh call.
let refreshPromise: Promise<boolean> | null = null

function tryRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const refreshToken = await getStoredRefreshToken()
      if (!refreshToken) return false
      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Client": "mobile" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
        if (!res.ok) {
          await clearTokens()
          return false
        }
        const data = (await res.json()) as AuthResponse
        if (!data.tokens) return false
        await storeTokens(data.tokens.access_token, data.tokens.refresh_token)
        return true
      } catch {
        return false
      }
    })().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
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
  getMatchLineups: (id: number) => apiFetch<MatchLineupsOut>(`/api/v1/matches/${id}/lineups`),
  getMatchStatistics: (id: number) => apiFetch<MatchStatisticsOut>(`/api/v1/matches/${id}/statistics`),
  getMatchPlayers: (id: number) => apiFetch<MatchPlayerStatisticsOut>(`/api/v1/matches/${id}/players`),
  getMatchForm: (id: number, scope: "overall" | "venue" = "overall") =>
    apiFetch<MatchFormOut>(`/api/v1/matches/${id}/form${query({ scope: scope === "overall" ? undefined : scope })}`),
  getMatchHeadToHead: (id: number) => apiFetch<HeadToHeadOut>(`/api/v1/matches/${id}/head-to-head`),

  getCompetitions: (page = 1, pageSize = 50) =>
    apiFetch<Page<CompetitionOut>>(`/api/v1/competitions${query({ page, page_size: pageSize })}`),
  getCompetition: (id: number) => apiFetch<CompetitionOut>(`/api/v1/competitions/${id}`),
  /** `scope`: "all" (default), "upcoming" (fixtures) or "results" (most recent first). */
  getCompetitionFixtures: (
    id: number,
    page = 1,
    pageSize = 50,
    scope: "all" | "upcoming" | "results" = "all",
  ) =>
    apiFetch<Page<MatchSummary>>(
      `/api/v1/competitions/${id}/fixtures${query({ page, page_size: pageSize, scope: scope === "all" ? undefined : scope })}`,
    ),
  getStandings: (id: number, season?: string, group?: string) =>
    apiFetch<StandingEntry[]>(`/api/v1/competitions/${id}/standings${query({ season, group })}`),
  getTopScorers: (id: number, season?: string) =>
    apiFetch<TopScorersOut>(`/api/v1/competitions/${id}/top-scorers${query({ season })}`),

  getTeam: (id: number) => apiFetch<TeamDetail>(`/api/v1/teams/${id}`),
  getTeamSquad: (id: number) => apiFetch<PlayerOut[]>(`/api/v1/teams/${id}/players`),
  getTeamStatistics: (id: number) => apiFetch<TeamStatisticsOut>(`/api/v1/teams/${id}/statistics`),
  getTeamForm: (id: number, scope: "overall" | "home" | "away" = "overall") =>
    apiFetch<TeamFormOut>(`/api/v1/teams/${id}/form${query({ scope: scope === "overall" ? undefined : scope })}`),

  getPlayer: (id: number) => apiFetch<PlayerDetail>(`/api/v1/players/${id}`),
  getPlayerStatistics: (id: number) => apiFetch<PlayerStatisticsOut>(`/api/v1/players/${id}/statistics`),

  getCapabilities: () => apiFetch<Capabilities>("/api/v1/capabilities"),
  getCompetitionSeasons: (id: number) =>
    apiFetch<CompetitionSeasonsOut>(`/api/v1/competitions/${id}/seasons`),
  getTeamFixtures: (id: number, page = 1, pageSize = 50) =>
    apiFetch<Page<MatchSummary>>(`/api/v1/teams/${id}/fixtures${query({ page, page_size: pageSize })}`),
  getTeamResults: (id: number, page = 1, pageSize = 50) =>
    apiFetch<Page<MatchSummary>>(`/api/v1/teams/${id}/results${query({ page, page_size: pageSize })}`),

  search: (q: string) => apiFetch<SearchResults>(`/api/v1/search${query({ q })}`),

  // -- Phase 3: auth ----------------------------------------------------------

  async register(email: string, password: string, displayName?: string): Promise<AuthResponse> {
    const response = await apiFetch<AuthResponse>("/api/v1/auth/register", {
      method: "POST",
      body: { email, password, password_confirm: password, display_name: displayName || undefined },
    })
    if (response.tokens) await storeTokens(response.tokens.access_token, response.tokens.refresh_token)
    return response
  },
  async login(email: string, password: string): Promise<AuthResponse> {
    const response = await apiFetch<AuthResponse>("/api/v1/auth/login", {
      method: "POST",
      body: { email, password },
    })
    if (response.tokens) await storeTokens(response.tokens.access_token, response.tokens.refresh_token)
    return response
  },
  async logout(): Promise<void> {
    const refreshToken = await getStoredRefreshToken()
    try {
      await apiFetch<void>("/api/v1/auth/logout", { method: "POST", body: { refresh_token: refreshToken } })
    } finally {
      await clearTokens()
    }
  },
  requestPasswordReset: (email: string) =>
    apiFetch<{ detail: string; dev_reset_url: string | null }>("/api/v1/auth/password-reset/request", {
      method: "POST",
      body: { email },
    }),
  confirmPasswordReset: (token: string, newPassword: string) =>
    apiFetch<void>("/api/v1/auth/password-reset/confirm", {
      method: "POST",
      body: { token, new_password: newPassword },
    }),

  getMe: () => apiFetch<UserOut>("/api/v1/users/me"),
  updateMe: (displayName: string | null) =>
    apiFetch<UserOut>("/api/v1/users/me", { method: "PATCH", body: { display_name: displayName } }),
  changePassword: (currentPassword: string, newPassword: string) =>
    apiFetch<void>("/api/v1/users/me/password", {
      method: "POST",
      body: { current_password: currentPassword, new_password: newPassword },
    }),

  // -- Phase 3: favourites ------------------------------------------------------

  getFavourites: () => apiFetch<FavouritesOut>("/api/v1/favourites"),
  followTeam: (teamId: number) => apiFetch<void>(`/api/v1/favourites/teams/${teamId}`, { method: "POST" }),
  unfollowTeam: (teamId: number) =>
    apiFetch<void>(`/api/v1/favourites/teams/${teamId}`, { method: "DELETE" }),
  followCompetition: (competitionId: number) =>
    apiFetch<void>(`/api/v1/favourites/competitions/${competitionId}`, { method: "POST" }),
  unfollowCompetition: (competitionId: number) =>
    apiFetch<void>(`/api/v1/favourites/competitions/${competitionId}`, { method: "DELETE" }),
  followMatch: (matchId: number) =>
    apiFetch<void>(`/api/v1/favourites/matches/${matchId}`, { method: "POST" }),
  unfollowMatch: (matchId: number) =>
    apiFetch<void>(`/api/v1/favourites/matches/${matchId}`, { method: "DELETE" }),

  // -- Phase 3: devices + notifications -------------------------------------------

  registerDevice: (payload: DeviceRegisterInput) =>
    apiFetch<DeviceOut>("/api/v1/devices", { method: "POST", body: payload }),
  getDevices: () => apiFetch<DeviceOut[]>("/api/v1/devices"),
  removeDevice: (deviceId: number) => apiFetch<void>(`/api/v1/devices/${deviceId}`, { method: "DELETE" }),

  getNotificationPreferences: () =>
    apiFetch<NotificationPreferenceOut[]>("/api/v1/notifications/preferences"),
  updateNotificationPreference: (
    scopeType: NotificationScope,
    scopeId: number | null,
    eventType: RealtimeEventType,
    enabled: boolean,
  ) =>
    apiFetch<NotificationPreferenceOut>("/api/v1/notifications/preferences", {
      method: "PATCH",
      body: { scope_type: scopeType, scope_id: scopeId, event_type: eventType, enabled },
    }),
  /** Remove one explicit override so the scope + event falls back to its default. */
  resetNotificationPreference: (
    scopeType: NotificationScope,
    scopeId: number | null,
    eventType: RealtimeEventType,
  ) =>
    apiFetch<void>(
      `/api/v1/notifications/preferences${query({ scope_type: scopeType, scope_id: scopeId ?? undefined, event_type: eventType })}`,
      { method: "DELETE" },
    ),
}
