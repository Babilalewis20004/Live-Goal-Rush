import { clearTokens, getStoredAccessToken, getStoredRefreshToken, storeTokens } from "@/lib/auth-storage"
import type {
  ArticleAdminOut,
  ArticleAdminSummary,
  ArticleDetail,
  ArticleInput,
  ArticleStatus,
  ArticleSummary,
  AuthResponse,
  Capabilities,
  CategoryOut,
  CommentOut,
  CommentPage,
  CommentTargetType,
  CompetitionOut,
  CompetitionSeasonsOut,
  ContentNotificationKind,
  ContentPreferenceOut,
  DeviceOut,
  DeviceRegisterInput,
  DiscoveryHome,
  FavouritesOut,
  AdPlacementOut,
  CheckoutOut,
  EntitlementsOut,
  FeedOut,
  InsightRecordOut,
  MatchComparisonOut,
  PersonalInsight,
  PlanOut,
  PlayerAnalyticsOut,
  PredictionEvaluationSummary,
  PredictionOut,
  ProfileReportOut,
  SubscriptionOut,
  TeamAnalyticsOut,
  FolderOut,
  HeadToHeadOut,
  MatchDetail,
  MatchFormOut,
  MatchInsightsOut,
  MatchLineupsOut,
  MatchPlayerStatisticsOut,
  MatchStatisticsOut,
  MatchSummary,
  MediaOut,
  MyProfileOut,
  NotificationPreferenceOut,
  NotificationScope,
  Page,
  PlayerDetail,
  PlayerOut,
  PlayerStatisticsOut,
  PollInput,
  PollOut,
  ProfileOut,
  ReactionKind,
  ReactionSummary,
  RealtimeEventType,
  ReportOut,
  RevisionDiff,
  RevisionOut,
  SearchResults,
  SearchSuggestions,
  StandingEntry,
  TeamDetail,
  TeamFormOut,
  TeamInjuriesOut,
  TeamInsightsOut,
  TeamStatisticsOut,
  TopScorersOut,
  TrackEntity,
  UserOut,
} from "@/types/api"

// The mobile app never talks to the football provider directly -- only to
// this backend, which is the same FastAPI service the web app uses.
const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000"

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** For a 402: the Premium entitlement the request needed. */
    public entitlement?: string,
  ) {
    super(message)
    this.name = "ApiError"
  }
}

interface ApiFetchOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE"
  body?: unknown
  /** A multipart upload (React Native FormData with a `{uri, name, type}` file part). */
  form?: FormData
  /** Internal: set on the retried request after a 401-triggered refresh,
   * so a second failure gives up instead of refreshing forever. */
  _retried?: boolean
}

/** A request that has not answered by now is treated as a failure, so a slow or half-dead network shows an error
 * (with retry) instead of a spinner that never ends. Uploads get longer. */
const REQUEST_TIMEOUT_MS = 15_000
const UPLOAD_TIMEOUT_MS = 60_000

// Mobile has no cookie jar to rely on (Phase 3 §5) -- every request carries
// its access token explicitly, and identifies itself as mobile so the auth
// endpoints return raw tokens in the body instead of only setting cookies.
async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Client": "mobile" }
  if (options.body !== undefined && !options.form) headers["Content-Type"] = "application/json"
  const accessToken = await getStoredAccessToken()
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`

  let res: Response
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), options.form ? UPLOAD_TIMEOUT_MS : REQUEST_TIMEOUT_MS)
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.form ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
      signal: controller.signal,
    })
  } catch {
    throw new ApiError(
      0,
      controller.signal.aborted
        ? "The football data service is taking too long to answer. Please try again."
        : "Unable to reach the football data service. Please try again.",
    )
  } finally {
    clearTimeout(timer)
  }

  if (res.status === 401 && !options._retried && !path.startsWith("/api/v1/auth/")) {
    const refreshed = await tryRefresh()
    if (refreshed) return apiFetch<T>(path, { ...options, _retried: true })
  }

  if (!res.ok) {
    if (res.status === 404) throw new ApiError(404, "Not found")
    let message = "The football data service returned an error. Please try again."
    let entitlement: string | undefined
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body?.detail === "string") message = body.detail
      else if (body?.detail && typeof body.detail === "object" && typeof (body.detail as { message?: unknown }).message === "string") {
        // 402 Payment Required: { message, entitlement }
        message = (body.detail as { message: string }).message
        const needed = (body.detail as { entitlement?: unknown }).entitlement
        if (typeof needed === "string") entitlement = needed
      }
    } catch {
      // Body wasn't JSON (or was empty) -- keep the generic message.
    }
    throw new ApiError(res.status, message, entitlement)
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

function query(params: Record<string, string | number | boolean | undefined>): string {
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
  /** Phase 7: everything the account holder has given us, as JSON (never credentials or other people's data). */
  exportMyData: () => apiFetch<Record<string, unknown>>("/api/v1/users/me/export"),
  /** Phase 7: irreversible erasure of the account's personal data; needs the current password. */
  deleteAccount: (password: string) =>
    apiFetch<void>("/api/v1/users/me", { method: "DELETE", body: { password } }),

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

  // -- Discovery: news --------------------------------------------------------------

  getArticles: (params: { page?: number; pageSize?: number; category?: string; tag?: string; featured?: boolean } = {}) =>
    apiFetch<Page<ArticleSummary>>(
      `/api/v1/articles${query({
        page: params.page,
        page_size: params.pageSize,
        category: params.category,
        tag: params.tag,
        featured: params.featured,
      })}`,
    ),
  getArticle: (slug: string) => apiFetch<ArticleDetail>(`/api/v1/articles/${encodeURIComponent(slug)}`),
  getRelatedArticles: (slug: string, limit = 4) =>
    apiFetch<ArticleSummary[]>(`/api/v1/articles/${encodeURIComponent(slug)}/related${query({ limit })}`),
  getArticleCategories: () => apiFetch<CategoryOut[]>("/api/v1/articles/categories"),
  getTeamNews: (id: number, page = 1, pageSize = 10) =>
    apiFetch<Page<ArticleSummary>>(`/api/v1/teams/${id}/news${query({ page, page_size: pageSize })}`),
  getPlayerNews: (id: number, page = 1, pageSize = 10) =>
    apiFetch<Page<ArticleSummary>>(`/api/v1/players/${id}/news${query({ page, page_size: pageSize })}`),
  getCompetitionNews: (id: number, page = 1, pageSize = 10) =>
    apiFetch<Page<ArticleSummary>>(`/api/v1/competitions/${id}/news${query({ page, page_size: pageSize })}`),
  getMatchNews: (id: number, page = 1, pageSize = 10) =>
    apiFetch<Page<ArticleSummary>>(`/api/v1/matches/${id}/news${query({ page, page_size: pageSize })}`),

  // -- Discovery: home, feed ------------------------------------------------------------

  getDiscoveryHome: () => apiFetch<DiscoveryHome>("/api/v1/discovery/home"),
  getFeed: () => apiFetch<FeedOut>("/api/v1/feed"),

  // -- Discovery: search ---------------------------------------------------------------------

  getSearchSuggestions: (q: string) => apiFetch<SearchSuggestions>(`/api/v1/search/suggestions${query({ q })}`),
  getPopularSearches: () => apiFetch<{ queries: string[] }>("/api/v1/search/popular"),
  getRecentSearches: () => apiFetch<{ queries: string[] }>("/api/v1/search/recent"),
  clearRecentSearches: (q?: string) => apiFetch<void>(`/api/v1/search/recent${query({ query: q })}`, { method: "DELETE" }),
  trackSearch: (q: string, entityType?: TrackEntity, entityId?: number) =>
    apiFetch<void>("/api/v1/search/track", {
      method: "POST",
      body: { query: q, entity_type: entityType, entity_id: entityId },
    }),
  trackView: (entityType: TrackEntity, id: number | string) =>
    apiFetch<void>("/api/v1/engagement/view", {
      method: "POST",
      body:
        entityType === "article" && typeof id === "string"
          ? { entity_type: entityType, slug: id }
          : { entity_type: entityType, entity_id: id },
    }),

  getContentPreferences: () => apiFetch<ContentPreferenceOut[]>("/api/v1/notifications/content-preferences"),
  setContentPreference: (kind: ContentNotificationKind, enabled: boolean) =>
    apiFetch<ContentPreferenceOut>("/api/v1/notifications/content-preferences", {
      method: "PUT",
      body: { kind, enabled },
    }),

  uploadMedia: (file: { uri: string; name: string; type: string }, opts: { folderId?: number; altText?: string } = {}) => {
    const form = new FormData()
    // React Native's FormData accepts a {uri, name, type} object as a file part.
    form.append("file", file as unknown as Blob)
    if (opts.folderId !== undefined) form.append("folder_id", String(opts.folderId))
    if (opts.altText) form.append("alt_text", opts.altText)
    return apiFetch<MediaOut>("/api/v1/editor/media", { method: "POST", form })
  },

  // -- Phase 6: media ------------------------------------------------------------------

  listMedia: (folderId?: number, page = 1) =>
    apiFetch<Page<MediaOut>>(`/api/v1/editor/media${query({ folder_id: folderId, page, page_size: 30 })}`),
  updateMedia: (id: number, input: { alt_text?: string; folder_id?: number; move_to_root?: boolean }) =>
    apiFetch<MediaOut>(`/api/v1/editor/media/${id}`, { method: "PATCH", body: input }),
  deleteMedia: (id: number) => apiFetch<void>(`/api/v1/editor/media/${id}`, { method: "DELETE" }),
  listFolders: () => apiFetch<FolderOut[]>("/api/v1/editor/media/folders"),
  createFolder: (name: string, parentId?: number) =>
    apiFetch<FolderOut>("/api/v1/editor/media/folders", { method: "POST", body: { name, parent_id: parentId ?? null } }),
  deleteFolder: (id: number) => apiFetch<void>(`/api/v1/editor/media/folders/${id}`, { method: "DELETE" }),
  setPlayerPhoto: (playerId: number, mediaId: number | null) =>
    apiFetch<MediaOut | null>(`/api/v1/editor/media/players/${playerId}/photo`, { method: "PUT", body: { media_id: mediaId } }),

  // -- Phase 6: editorial workflow, scheduling, revisions ------------------------------------

  submitArticle: (id: number) => apiFetch<ArticleAdminOut>(`/api/v1/editor/articles/${id}/submit`, { method: "POST" }),
  withdrawArticle: (id: number) => apiFetch<ArticleAdminOut>(`/api/v1/editor/articles/${id}/withdraw`, { method: "POST" }),
  approveArticle: (id: number, input: { publish_at?: string; unpublish_at?: string } = {}) =>
    apiFetch<ArticleAdminOut>(`/api/v1/editor/articles/${id}/approve`, { method: "POST", body: input }),
  rejectArticle: (id: number, note: string) =>
    apiFetch<ArticleAdminOut>(`/api/v1/editor/articles/${id}/reject`, { method: "POST", body: { note } }),
  scheduleArticle: (id: number, publishAt: string, unpublishAt?: string) =>
    apiFetch<ArticleAdminOut>(`/api/v1/editor/articles/${id}/schedule`, {
      method: "POST",
      body: { publish_at: publishAt, unpublish_at: unpublishAt ?? null },
    }),
  listRevisions: (id: number) => apiFetch<RevisionOut[]>(`/api/v1/editor/articles/${id}/revisions`),
  compareRevisions: (id: number, from: number, to: number) =>
    apiFetch<RevisionDiff>(`/api/v1/editor/articles/${id}/revisions/compare${query({ from_version: from, to_version: to })}`),
  restoreRevision: (id: number, version: number) =>
    apiFetch<ArticleAdminOut>(`/api/v1/editor/articles/${id}/revisions/${version}/restore`, { method: "POST" }),

  // -- Phase 6: comments & moderation ---------------------------------------------------------

  getComments: (type: CommentTargetType, id: number, opts: { sort?: "newest" | "top"; page?: number; pageSize?: number } = {}) =>
    apiFetch<CommentPage>(
      `/api/v1/comments${query({ target_type: type, target_id: id, sort: opts.sort, page: opts.page, page_size: opts.pageSize })}`,
    ),
  postComment: (type: CommentTargetType, id: number, body: string, parentId?: number) =>
    apiFetch<CommentOut>("/api/v1/comments", {
      method: "POST",
      body: { target_type: type, target_id: id, body, parent_id: parentId ?? null },
    }),
  editComment: (id: number, body: string) =>
    apiFetch<CommentOut>(`/api/v1/comments/${id}`, { method: "PATCH", body: { body } }),
  deleteComment: (id: number) => apiFetch<void>(`/api/v1/comments/${id}`, { method: "DELETE" }),
  likeComment: (id: number) =>
    apiFetch<{ like_count: number; liked_by_me: boolean }>(`/api/v1/comments/${id}/like`, { method: "PUT" }),
  unlikeComment: (id: number) =>
    apiFetch<{ like_count: number; liked_by_me: boolean }>(`/api/v1/comments/${id}/like`, { method: "DELETE" }),
  reportComment: (id: number, reason: string) =>
    apiFetch<void>(`/api/v1/comments/${id}/report`, { method: "POST", body: { reason } }),
  getReports: (status: "open" | "resolved" | "dismissed" = "open", page = 1) =>
    apiFetch<Page<ReportOut>>(`/api/v1/moderation/reports${query({ status, page, page_size: 20 })}`),
  moderateComment: (id: number, action: "hide" | "restore" | "delete") =>
    apiFetch<void>(`/api/v1/moderation/comments/${id}`, { method: "POST", body: { action } }),

  // -- Phase 6: reactions & polls ----------------------------------------------------------------

  getReactions: (type: CommentTargetType, id: number) => apiFetch<ReactionSummary>(`/api/v1/reactions/${type}/${id}`),
  react: (type: CommentTargetType, id: number, kind: ReactionKind) =>
    apiFetch<ReactionSummary>(`/api/v1/reactions/${type}/${id}`, { method: "PUT", body: { kind } }),
  unreact: (type: CommentTargetType, id: number) =>
    apiFetch<ReactionSummary>(`/api/v1/reactions/${type}/${id}`, { method: "DELETE" }),
  getPolls: (opts: { matchId?: number; articleId?: number; status?: "open" | "closed"; standalone?: boolean; limit?: number } = {}) =>
    apiFetch<PollOut[]>(
      `/api/v1/polls${query({ match_id: opts.matchId, article_id: opts.articleId, status: opts.status, standalone: opts.standalone, limit: opts.limit })}`,
    ),
  getPoll: (id: number) => apiFetch<PollOut>(`/api/v1/polls/${id}`),
  votePoll: (pollId: number, optionId: number) =>
    apiFetch<PollOut>(`/api/v1/polls/${pollId}/vote`, { method: "POST", body: { option_id: optionId } }),
  createPoll: (input: PollInput) => apiFetch<PollOut>("/api/v1/editor/polls", { method: "POST", body: input }),
  closePoll: (id: number) => apiFetch<PollOut>(`/api/v1/editor/polls/${id}/close`, { method: "POST" }),
  deletePoll: (id: number) => apiFetch<void>(`/api/v1/editor/polls/${id}`, { method: "DELETE" }),

  // -- Phase 6: profiles & insights ------------------------------------------------------------------

  getMyProfile: () => apiFetch<MyProfileOut>("/api/v1/users/me/profile"),
  updateMyProfile: (input: { profile_public?: boolean; bio?: string | null }) =>
    apiFetch<MyProfileOut>("/api/v1/users/me/profile", { method: "PATCH", body: input }),
  getProfile: (id: number) => apiFetch<ProfileOut>(`/api/v1/profiles/${id}`),
  getTeamInsights: (id: number) => apiFetch<TeamInsightsOut>(`/api/v1/teams/${id}/insights`),
  getTeamInjuries: (id: number) => apiFetch<TeamInjuriesOut>(`/api/v1/teams/${id}/injuries`),
  getMatchInsights: (id: number) => apiFetch<MatchInsightsOut>(`/api/v1/matches/${id}/insights`),

  // -- Editorial (author / editor / admin) ------------------------------------------------

  listEditorArticles: (status?: ArticleStatus, page = 1) =>
    apiFetch<Page<ArticleAdminSummary>>(`/api/v1/editor/articles${query({ status, page, page_size: 50 })}`),
  getEditorArticle: (id: number) => apiFetch<ArticleAdminOut>(`/api/v1/editor/articles/${id}`),
  getEditorCategories: () => apiFetch<CategoryOut[]>("/api/v1/editor/articles/categories"),
  createArticle: (input: ArticleInput) => apiFetch<ArticleAdminOut>("/api/v1/editor/articles", { method: "POST", body: input }),
  updateArticle: (id: number, input: Partial<ArticleInput>) =>
    apiFetch<ArticleAdminOut>(`/api/v1/editor/articles/${id}`, { method: "PATCH", body: input }),
  setArticleStatus: (id: number, action: "publish" | "unpublish" | "archive") =>
    apiFetch<ArticleAdminOut>(`/api/v1/editor/articles/${id}/${action}`, { method: "POST" }),

  // -- Phase 6b: analytics, predictions, insights ----------------------------------------------------
  // The server decides what each caller may see; a 402 carries the missing entitlement.

  getTeamAnalytics: (id: number, opts: { scope?: "overall" | "home" | "away"; window?: number } = {}) =>
    apiFetch<TeamAnalyticsOut>(`/api/v1/teams/${id}/analytics${query({ scope: opts.scope, window: opts.window })}`),
  getPlayerAnalytics: (id: number, window?: number) =>
    apiFetch<PlayerAnalyticsOut>(`/api/v1/players/${id}/analytics${query({ window })}`),
  getMatchComparison: (id: number) => apiFetch<MatchComparisonOut>(`/api/v1/matches/${id}/comparison`),
  getMatchPrediction: (id: number) => apiFetch<PredictionOut>(`/api/v1/matches/${id}/prediction`),
  getExtendedHeadToHead: (id: number, window: "last5" | "last10" | "all") =>
    apiFetch<HeadToHeadOut>(`/api/v1/matches/${id}/head-to-head/extended${query({ window })}`),
  getMatchInsightRecords: (id: number) => apiFetch<InsightRecordOut[]>(`/api/v1/matches/${id}/insight-records`),
  getPlayerInsights: (id: number) => apiFetch<InsightRecordOut[]>(`/api/v1/players/${id}/insights`),
  getPredictionEvaluation: () => apiFetch<PredictionEvaluationSummary>("/api/v1/predictions/evaluation"),
  getMyInsights: () => apiFetch<PersonalInsight[]>("/api/v1/me/insights"),

  // -- Phase 6b: premium -----------------------------------------------------------------------------------

  getEntitlements: () => apiFetch<EntitlementsOut>("/api/v1/me/entitlements"),
  getPlans: () => apiFetch<PlanOut[]>("/api/v1/subscription/plans"),
  getSubscription: () => apiFetch<SubscriptionOut>("/api/v1/subscription"),
  startCheckout: (planCode: string) =>
    apiFetch<CheckoutOut>("/api/v1/subscription/checkout", { method: "POST", body: { plan_code: planCode } }),
  cancelSubscription: () => apiFetch<SubscriptionOut>("/api/v1/subscription/cancel", { method: "POST" }),
  getAdPlacements: (live = false) => apiFetch<AdPlacementOut[]>(`/api/v1/ads/placements${query({ live: live || undefined })}`),

  // -- Phase 6b: moderation --------------------------------------------------------------------------------

  reportProfile: (userId: number, reason: string) =>
    apiFetch<void>(`/api/v1/profiles/${userId}/report`, { method: "POST", body: { reason } }),
  listProfileReports: (status: "open" | "resolved" | "dismissed" = "open", page = 1) =>
    apiFetch<Page<ProfileReportOut>>(`/api/v1/moderation/profile-reports${query({ status, page })}`),
  resolveProfileReport: (id: number, action: "resolve" | "dismiss") =>
    apiFetch<void>(`/api/v1/moderation/profile-reports/${id}/${action}`, { method: "POST" }),

}
