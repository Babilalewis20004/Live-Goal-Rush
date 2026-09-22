import { NextResponse, type NextRequest } from "next/server"

/** UX-only gate (Phase 3): avoids a flash of a protected page before it
 * redirects. Real enforcement stays server-side (`CurrentUserDep` on the
 * API) -- this only checks the `access_token` cookie's *presence*, not its
 * signature, which is enough to decide whether to render the page at all
 * and cheap enough to run on every request to these paths. Named `proxy`,
 * not `middleware` -- Next.js 16 renamed the convention (functionality is
 * unchanged; see node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md). */
const PROTECTED_PREFIXES = ["/profile", "/favourites", "/settings"]

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl
  const isProtected = PROTECTED_PREFIXES.some((prefix) => pathname.startsWith(prefix))
  if (!isProtected) return NextResponse.next()

  const hasSession = request.cookies.has("access_token")
  if (hasSession) return NextResponse.next()

  const loginUrl = new URL("/login", request.url)
  loginUrl.searchParams.set("next", pathname)
  return NextResponse.redirect(loginUrl)
}

export const config = {
  matcher: ["/profile/:path*", "/favourites/:path*", "/settings/:path*"],
}
