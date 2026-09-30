/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
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
