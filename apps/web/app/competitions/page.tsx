import Link from "next/link"
import { AnimatedBackground } from "@/components/animated-background"
import { CompetitionCard } from "@/components/competition-card"
import { EmptyState } from "@/components/ui/empty-state"
import { api } from "@/lib/api"

export const dynamic = "force-dynamic"

export default async function CompetitionsPage() {
  const { items } = await api.getCompetitions()

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-2xl px-4 pb-16 pt-6">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>

        <h1 className="mt-4 mb-4 text-lg font-bold text-white">Competitions</h1>

        {items.length === 0 ? (
          <EmptyState message="No competitions available." />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {items.map((competition) => (
              <CompetitionCard key={competition.id} competition={competition} />
            ))}
          </div>
        )}
      </div>
    </main>
  )
}
