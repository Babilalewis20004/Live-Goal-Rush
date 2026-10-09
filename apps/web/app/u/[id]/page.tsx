import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"

import { AnimatedBackground } from "@/components/animated-background"
import { ReportProfile } from "@/components/community/report-profile"
import { api, ApiError } from "@/lib/api"
import { relativeTime } from "@/lib/community"

export const dynamic = "force-dynamic"

// A person's page is theirs, not a search result: kept out of the index.
export const metadata: Metadata = { title: "Profile", robots: { index: false, follow: false } }

export default async function PublicProfilePage({ params }: { params: Promise<{ id: string }> }) {
  const userId = Number((await params).id)
  if (!Number.isInteger(userId) || userId < 1) notFound()
  let profile
  try {
    profile = await api.getProfile(userId)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound() // private and missing look the same
    throw error
  }

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-xl px-4 pb-16 pt-8">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>
        <header className="mt-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md">
          <h1 className="text-xl font-bold text-white">{profile.display_name}</h1>
          <p className="mt-0.5 text-xs text-white/45">
            Joined {new Date(profile.joined).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" })}
          </p>
          {profile.bio && <p className="mt-3 whitespace-pre-wrap text-sm text-white/80">{profile.bio}</p>}
          {profile.badges.length > 0 && (
            <ul className="mt-4 flex flex-wrap gap-2" aria-label="Badges">
              {profile.badges.map((b) => (
                <li key={b.key} title={b.description} className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs text-white/80">
                  {b.label}
                </li>
              ))}
            </ul>
          )}
          <dl className="mt-4 grid grid-cols-3 gap-3 text-center text-xs">
            {[
              ["Comments", profile.stats.comments],
              ["Poll votes", profile.stats.poll_votes],
              ["Teams followed", profile.stats.followed_teams],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl bg-white/[0.04] px-2 py-2">
                <dt className="text-white/45">{label}</dt>
                <dd className="mt-0.5 text-base font-semibold text-white">{value}</dd>
              </div>
            ))}
          </dl>
          <ReportProfile userId={userId} />
        </header>

        {(profile.favourite_teams.length > 0 || profile.favourite_competitions.length > 0) && (
          <section aria-labelledby="follows" className="mt-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5">
            <h2 id="follows" className="mb-2 text-sm font-semibold text-white">
              Follows
            </h2>
            <ul className="flex flex-wrap gap-2">
              {profile.favourite_teams.map((t) => (
                <li key={`t${t.id}`}>
                  <Link href={`/team/${t.id}`} className="inline-flex min-h-8 items-center rounded-full border border-white/10 bg-white/[0.04] px-3 text-xs text-white/80 hover:bg-white/[0.08]">
                    {t.name}
                  </Link>
                </li>
              ))}
              {profile.favourite_competitions.map((c) => (
                <li key={`c${c.id}`}>
                  <Link href={`/competition/${c.id}`} className="inline-flex min-h-8 items-center rounded-full border border-white/10 bg-white/[0.04] px-3 text-xs text-white/80 hover:bg-white/[0.08]">
                    {c.name}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        {profile.activity.length > 0 && (
          <section aria-labelledby="activity" className="mt-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5">
            <h2 id="activity" className="mb-3 text-sm font-semibold text-white">
              Recent comments
            </h2>
            <ul className="space-y-3">
              {profile.activity.map((a, i) => (
                <li key={i} className="text-sm">
                  <p className="whitespace-pre-wrap break-words text-white/85">{a.text}</p>
                  <p className="mt-0.5 text-[11px] text-white/40">
                    on{" "}
                    <Link href={a.target_type === "article" && a.target_slug ? `/article/${a.target_slug}` : `/match/${a.target_id}`} className="underline hover:text-white">
                      {a.target_label}
                    </Link>{" "}
                    · {relativeTime(a.created_at)}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </main>
  )
}
