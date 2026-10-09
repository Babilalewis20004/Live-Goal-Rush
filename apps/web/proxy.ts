import { NextResponse, type NextRequest } from "next/server"

import { buildCsp, generateNonce } from "@/lib/csp"

/** Two jobs, both before a page renders (Next.js 16 calls this convention `proxy`, formerly `middleware`;
 * see node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md):
 *
 * 1. UX-only gate (Phase 3): avoids a flash of a protected page before it redirects. Real enforcement
 *    stays server-side (`CurrentUserDep` on the API) -- this only checks the `access_token` cookie's
 *    *presence*, not its signature.
 * 2. Content-Security-Policy with a per-request nonce (Phase 7), see `lib/csp.ts`. */
const PROTECTED_PREFIXES = ["/profile", "/favourites", "/settings", "/editor"]

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl
  const isProtected = PROTECTED_PREFIXES.some((prefix) => pathname.startsWith(prefix))

  if (isProtected && !request.cookies.has("access_token")) {
    const loginUrl = new URL("/login", request.url)
    loginUrl.searchParams.set("next", pathname)
    return NextResponse.redirect(loginUrl)
  }

  const nonce = generateNonce()
  const csp = buildCsp({
    nonce,
    isDev: process.env.NODE_ENV === "development",
    apiUrl: process.env.NEXT_PUBLIC_BROWSER_API_URL ?? process.env.NEXT_PUBLIC_API_URL,
    wsUrl: process.env.NEXT_PUBLIC_WS_URL,
    siteUrl: process.env.NEXT_PUBLIC_SITE_URL,
  })

  // Next.js reads the nonce from the *request's* CSP header while rendering and stamps it on its scripts.
  const requestHeaders = new Headers(request.headers)
  requestHeaders.set("x-nonce", nonce)
  requestHeaders.set("Content-Security-Policy", csp)

  const response = NextResponse.next({ request: { headers: requestHeaders } })
  response.headers.set("Content-Security-Policy", csp)
  return response
}

export const config = {
  matcher: [
    {
      // Pages only: static assets and the metadata files need neither a nonce nor the auth gate.
      source: "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
}
