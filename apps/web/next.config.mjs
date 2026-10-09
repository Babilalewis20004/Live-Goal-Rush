/** @type {import('next').NextConfig} */
// Headers that do not depend on the request. The Content-Security-Policy is per request (it carries a
// nonce) and is set in proxy.ts. HSTS is ignored by browsers over plain HTTP, so it is safe to send always.
// Hosts whose crests are resized by the image optimizer. Also read by lib/images.ts (hence NEXT_PUBLIC_).
const crestImageHosts = (process.env.NEXT_PUBLIC_CREST_IMAGE_HOSTS ?? "media.api-sports.io,crests.football-data.org")
  .split(",")
  .map((host) => host.trim())
  .filter(Boolean)

const securityHeaders = [
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
]

const nextConfig = {
  // Type errors fail the build (they were silently ignored before Phase 7; `npm run typecheck` is clean).
  poweredByHeader: false,
  // Team and league crests come from the football data provider as large originals (89-116 KB PNGs) but are shown at
  // 26-64 px: the home page transferred over 1 MB, mostly crests. They go through Next's optimizer (resized, WebP, cached)
  // -- but only from the hosts listed here, so /_next/image is not an open proxy. Everything else (article images, our own
  // media, SVG) is served as-is via `unoptimized` on the <Image>; see lib/images.ts.
  images: {
    remotePatterns: crestImageHosts.map((hostname) => ({ protocol: "https", hostname })),
    formats: ["image/webp"],
    minimumCacheTTL: 60 * 60 * 24,
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }]
  },
  // Phase 4 §36: stable plural/alias deep links (e.g. from notifications or
  // shared URLs) land on the existing singular routes.
  async redirects() {
    return [
      { source: "/matches/:id(\\d+)", destination: "/match/:id", permanent: false },
      { source: "/teams/:id(\\d+)", destination: "/team/:id", permanent: false },
      { source: "/competitions/:id(\\d+)", destination: "/competition/:id", permanent: false },
      { source: "/players/:id(\\d+)", destination: "/player/:id", permanent: false },
    ]
  },
}

export default nextConfig
