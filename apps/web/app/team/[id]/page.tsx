import type { Metadata } from "next"
import { notFound } from "next/navigation"
import Link from "next/link"
import { cache } from "react"
import { AnimatedBackground } from "@/components/animated-background"
import { ShareButton } from "@/components/news/share-button"
import { TrackView } from "@/components/news/track-view"
import { TeamCentre } from "@/components/team-centre"
import { TeamHeader } from "@/components/team-header"
import { api, ApiError } from "@/lib/api"
import { absoluteUrl, jsonLdScript, teamJsonLd, teamMetadata } from "@/lib/seo"
import { getServerFavourites } from "@/lib/server-auth"

export const dynamic = "force-dynamic"

async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch {
    return null
  }
}

// One fetch per request even though both generateMetadata and the page need it.
const loadTeam = cache(async (teamId: number) => {
  try {
    return await api.getTeam(teamId)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
})

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const teamId = Number((await params).id)
  const team = Number.isInteger(teamId) ? await loadTeam(teamId) : null
  if (!team) return { title: "Team not found", robots: { index: false, follow: false } }
  return teamMetadata(team)
}

export default async function TeamPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const teamId = Number(id)
  if (!Number.isInteger(teamId)) notFound()

  const team = await loadTeam(teamId)
  if (!team) notFound()

  const [fixtures, results, favourites, capabilities, overall, home, away, squad, statistics, news, insights, injuries] = await Promise.all([
    api.getTeamFixtures(teamId),
    api.getTeamResults(teamId, 1, 20),
    getServerFavourites(),
    optional(api.getCapabilities()),
    optional(api.getTeamForm(teamId, "overall")),
    optional(api.getTeamForm(teamId, "home")),
    optional(api.getTeamForm(teamId, "away")),
    optional(api.getTeamSquad(teamId)),
    optional(api.getTeamStatistics(teamId)),
    optional(api.getTeamNews(teamId)),
    optional(api.getTeamInsights(teamId)),
    optional(api.getTeamInjuries(teamId)),
  ])
  const initialFollowed = favourites?.teams.some((f) => f.team.id === teamId) ?? false

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript(teamJsonLd(team)) }} />
      <TrackView entity="team" id={teamId} />
      <div className="mx-auto max-w-3xl px-4 pb-16 pt-6">
        <div className="flex items-center justify-between">
          <Link href="/" className="text-xs text-white/50 hover:text-white/80">
            ← Back to livescores
          </Link>
          <ShareButton url={absoluteUrl(`/team/${teamId}`)} title={team.name} />
        </div>

        <div className="mt-4">
          <TeamHeader team={team} initialFollowed={initialFollowed} />
        </div>

        <div className="mt-4">
          <TeamCentre
            data={{
              team,
              fixtures: fixtures.items,
              results: results.items,
              form: { overall, home, away },
              squad,
              statistics,
              capabilities,
              news,
              insights,
              injuries,
            }}
          />
        </div>
      </div>
    </main>
  )
}
