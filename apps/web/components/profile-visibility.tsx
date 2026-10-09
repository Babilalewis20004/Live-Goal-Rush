"use client"

import Link from "next/link"
import { useState } from "react"

import { ApiError, api } from "@/lib/api"
import type { MyProfileOut } from "@/types/api"

/** Public-profile switch, bio and badges on the account page. The profile is private
 * until this is switched on; what becomes visible is listed right here. */
export function ProfileVisibility({ initial }: { initial: MyProfileOut }) {
  const [profile, setProfile] = useState(initial)
  const [bio, setBio] = useState(initial.bio ?? "")
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  async function save(update: { profile_public?: boolean; bio?: string | null }, success: string) {
    setBusy(true)
    setMessage(null)
    try {
      const next = await api.updateMyProfile(update)
      setProfile(next)
      setBio(next.bio ?? "")
      setMessage({ kind: "ok", text: success })
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "Couldn't save that." })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-labelledby="public-profile" className="mb-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 id="public-profile" className="text-sm font-semibold text-white">
        Public profile
      </h2>
      <p className="mt-1 text-xs text-white/50">
        Off by default. When on, anyone can see your display name, bio, badges, the teams and competitions you follow, and your recent public comments — never your email.
      </p>

      <label className="mt-3 flex items-center justify-between gap-4 text-sm text-white">
        Make my profile public
        <input
          type="checkbox"
          role="switch"
          checked={profile.profile_public}
          disabled={busy}
          onChange={(e) => void save({ profile_public: e.target.checked }, e.target.checked ? "Your profile is public." : "Your profile is private.")}
          className="h-5 w-5 accent-emerald-400"
        />
      </label>

      <div className="mt-3">
        <label htmlFor="bio" className="block text-xs font-medium text-white/60">
          Bio
        </label>
        <textarea
          id="bio"
          rows={2}
          maxLength={280}
          value={bio}
          onChange={(e) => setBio(e.target.value)}
          className="mt-1 w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-emerald-400/60 focus:outline-none focus:ring-2 focus:ring-emerald-400/30"
          placeholder="A line about you (optional)"
        />
        <button
          type="button"
          disabled={busy || bio === (profile.bio ?? "")}
          onClick={() => void save({ bio }, "Bio saved.")}
          className="mt-2 min-h-9 rounded-lg border border-white/10 bg-white/[0.05] px-3 text-xs text-white/80 hover:bg-white/[0.1] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
        >
          Save bio
        </button>
      </div>

      {profile.badges.length > 0 && (
        <ul className="mt-4 flex flex-wrap gap-2" aria-label="Your badges">
          {profile.badges.map((b) => (
            <li key={b.key} title={b.description} className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs text-white/80">
              {b.label}
            </li>
          ))}
        </ul>
      )}
      {profile.profile_public && (
        <p className="mt-3 text-xs">
          <Link href={`/u/${profile.id}`} className="text-emerald-300 underline hover:text-emerald-200">
            View your public profile →
          </Link>
        </p>
      )}
      {message && (
        <p role={message.kind === "error" ? "alert" : "status"} className={`mt-2 text-xs ${message.kind === "error" ? "text-red-300" : "text-emerald-300"}`}>
          {message.text}
        </p>
      )}
    </section>
  )
}
