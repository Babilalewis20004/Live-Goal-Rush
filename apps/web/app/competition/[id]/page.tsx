import type { Metadata } from "next"
import { notFound } from "next/navigation"
import Link from "next/link"
import { cache } from "react"
import { AnimatedBackground } from "@/components/animated-background"
import { CompetitionCentre } from "@/components/competition-centre"
import { CompetitionHeader } from "@/components/competition-header"
import { ShareButton } from "@/components/news/share-button"
import { TrackView } from "@/components/news/track-view"
import { api, ApiError } from "@/lib/api"
import { absoluteUrl, competitionJsonLd, competitionMetadata, jsonLdScript } from "@/lib/seo"
import { getServerFavourites } from "@/lib/server-auth"

export const dynamic = "force-dynamic"

async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch {
    return null
  }
}

const loadCompetition = cache(async (competitionId: number) => {
  try {
    return await api.getCompetition(competitionId)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
})

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const competitionId = Number((await params).id)
  const competition = Number.isInteger(competitionId) ? await loadCompetition(competitionId) : null
  if (!competition) return { title: "Competition not found", robots: { index: false, follow: false } }
  return competitionMetadata(competition)
}

export default async function CompetitionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const competitionId = Number(id)
  if (!Number.isInteger(competitionId)) notFound()

  const competition = await loadCompetition(competitionId)
  if (!competition) notFound()

  const [fixtures, results, standings, topScorers, capabilities, seasons, favourites, news] = await Promise.all([
    api.getCompetitionFixtures(competitionId, 1, 50, "upcoming"),
    api.getCompetitionFixtures(competitionId, 1, 50, "results"),
    optional(api.getStandings(competitionId)),
    optional(api.getTopScorers(competitionId)),
    optional(api.getCapabilities()),
    optional(api.getCompetitionSeasons(competitionId)),
    getServerFavourites(),
    optional(api.getCompetitionNews(competitionId)),
  ])
  const initialFollowed = favourites?.competitions.some((f) => f.competition.id === competitionId) ?? false

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript(competitionJsonLd(competition)) }} />
      <TrackView entity="competition" id={competitionId} />
      <div className="mx-auto max-w-3xl px-4 pb-16 pt-6">
        <div className="flex items-center justify-between">
          <Link href="/" className="text-xs text-white/50 hover:text-white/80">
            ← Back to livescores
          </Link>
          <ShareButton url={absoluteUrl(`/competition/${competitionId}`)} title={competition.name} />
        </div>

        <div className="mt-4">
          <CompetitionHeader competition={competition} initialFollowed={initialFollowed} />
        </div>

        <div className="mt-4">
          <CompetitionCentre
            data={{
              competitionId,
              seasons,
              standings,
              fixtures: fixtures.items,
              results: results.items,
              topScorers,
              capabilities,
              news,
            }}
          />
        </div>
      </div>
    </main>
  )
}
