import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"

import { AnimatedBackground } from "@/components/animated-background"
import { PollCard } from "@/components/community/poll-card"
import { api, ApiError } from "@/lib/api"
import { pageMetadata } from "@/lib/seo"

export const dynamic = "force-dynamic"

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const id = Number((await params).id)
  const poll = Number.isInteger(id) ? await api.getPoll(id).catch(() => null) : null
  if (!poll) return { title: "Poll not found", robots: { index: false, follow: false } }
  return pageMetadata({ title: poll.question, description: `Vote and see the result: ${poll.question}`, path: `/poll/${poll.id}` })
}

export default async function PollPage({ params }: { params: Promise<{ id: string }> }) {
  const id = Number((await params).id)
  if (!Number.isInteger(id) || id < 1) notFound()
  let poll
  try {
    poll = await api.getPoll(id)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound()
    throw error
  }
  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-xl px-4 pb-16 pt-8">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>
        <h1 className="sr-only">Poll</h1>
        <div className="mt-4">
          <PollCard poll={poll} />
        </div>
        {poll.match_id && (
          <p className="mt-4 text-sm">
            <Link href={`/match/${poll.match_id}`} className="text-emerald-300 underline hover:text-emerald-200">
              Go to the match →
            </Link>
          </p>
        )}
      </div>
    </main>
  )
}
