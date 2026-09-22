import { AnimatedBackground } from "@/components/animated-background"
import { LivescoreBoard } from "@/components/livescore-board"
import { PersonalizedHome } from "@/components/personalized-home"
import { api } from "@/lib/api"

// Live scores must never be static-generated or cached across builds/deploys.
export const dynamic = "force-dynamic"

export default async function Page() {
  const [live, today, upcoming] = await Promise.all([
    api.getLiveMatches(),
    api.getTodayMatches(),
    api.getUpcomingMatches(),
  ])

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <PersonalizedHome liveMatches={live} />
      <LivescoreBoard live={live} today={today} upcoming={upcoming} />
    </main>
  )
}
