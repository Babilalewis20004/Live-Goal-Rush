import { AdSlot } from "@/components/analytics/ad-slot"
import { PersonalInsights } from "@/components/community/personal-insights"
import { AnimatedBackground } from "@/components/animated-background"
import { DiscoverySections } from "@/components/discovery/discovery-sections"
import { LivescoreBoard } from "@/components/livescore-board"
import { PersonalizedHome } from "@/components/personalized-home"
import { api } from "@/lib/api"
import { pageMetadata } from "@/lib/seo"

// Live scores must never be static-generated or cached across builds/deploys.
export const dynamic = "force-dynamic"

export const metadata = pageMetadata({
  title: "Live Football Scores, News & Results",
  description:
    "Live football scores, fixtures, results, tables and news for the leagues you follow — Champions League, Premier League, LaLiga, Serie A, Bundesliga and more.",
  path: "/",
})
// The root layout appends the site name to page titles; the home page is the site.
metadata.title = { absolute: "LivePitch · Live Football Scores, News & Results" }

export default async function Page() {
  const [live, today, upcoming, discovery] = await Promise.all([
    api.getLiveMatches(),
    api.getTodayMatches(),
    api.getUpcomingMatches(),
    // News, trending and results are additive: if they fail, the scoreboard still loads.
    api.getDiscoveryHome().catch(() => null),
  ])

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <PersonalizedHome liveMatches={live} />
      <div className="mx-auto max-w-2xl px-4">
        <PersonalInsights />
      </div>
      <LivescoreBoard live={live} today={today} upcoming={upcoming} />
      <DiscoverySections home={discovery} />
      <div className="mx-auto max-w-2xl px-4">
        <AdSlot placement="home" />
      </div>
    </main>
  )
}
