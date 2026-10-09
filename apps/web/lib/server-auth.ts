import { cookies } from "next/headers"

import { api, ApiError } from "@/lib/api"
import type { ContentPreferenceOut, FavouritesOut, NotificationPreferenceOut, UserOut } from "@/types/api"

/** Server Components run in this container, not the browser -- there's no
 * cookie jar for `fetch`'s `credentials: "include"` to act on, so the
 * incoming request's cookies are forwarded by hand as a `Cookie` header.
 * Returns `null` for an anonymous visitor (no cookie, or an expired/invalid
 * one) rather than throwing -- callers treat that as "show the public
 * view", matching the requirement that personalisation is additive. */
export async function getServerUser(): Promise<UserOut | null> {
  const cookieHeader = await buildCookieHeader()
  if (!cookieHeader) return null
  try {
    return await api.getMe(cookieHeader)
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 404)) return null
    throw error
  }
}

export async function getServerFavourites(): Promise<FavouritesOut | null> {
  const cookieHeader = await buildCookieHeader()
  if (!cookieHeader) return null
  try {
    return await api.getFavourites(cookieHeader)
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}

export async function getServerNotificationPreferences(): Promise<NotificationPreferenceOut[]> {
  const cookieHeader = await buildCookieHeader()
  if (!cookieHeader) return []
  try {
    return await api.getNotificationPreferences(cookieHeader)
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return []
    throw error
  }
}

export async function getServerContentPreferences(): Promise<ContentPreferenceOut[]> {
  const cookieHeader = await buildCookieHeader()
  if (!cookieHeader) return []
  try {
    return await api.getContentPreferences(cookieHeader)
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return []
    throw error
  }
}

/** The incoming request's cookies as a `Cookie` header, for Server Components
 * that call an authenticated endpoint on the visitor's behalf. */
export async function getServerCookieHeader(): Promise<string | null> {
  return buildCookieHeader()
}

async function buildCookieHeader(): Promise<string | null> {
  const store = await cookies()
  const all = store.getAll()
  if (all.length === 0) return null
  return all.map((c) => `${c.name}=${c.value}`).join("; ")
}
