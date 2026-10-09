import { redirect } from "next/navigation"
import Link from "next/link"

import { AnimatedBackground } from "@/components/animated-background"
import { ChangePasswordForm, UpdateProfileForm } from "@/components/profile-forms"
import { PrivacyData } from "@/components/privacy-data"
import { ProfileVisibility } from "@/components/profile-visibility"
import { getServerCookieHeader } from "@/lib/server-auth"
import { api } from "@/lib/api"
import { getServerUser } from "@/lib/server-auth"

export const dynamic = "force-dynamic"

export default async function ProfilePage() {
  const user = await getServerUser()
  if (!user) redirect("/login")
  const cookie = await getServerCookieHeader()
  const profile = await api.getMyProfile(cookie ?? undefined).catch(() => null)

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-sm px-4 pb-16 pt-10">
        <h1 className="mb-1 text-lg font-bold text-white">Your profile</h1>
        <p className="mb-6 text-xs text-white/40">{user.email}</p>

        <section className="mb-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md">
          <UpdateProfileForm user={user} />
        </section>

        {profile && <ProfileVisibility initial={profile} />}

        <section className="mb-4 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md">
          <h2 className="mb-3 text-sm font-semibold text-white">Change password</h2>
          <ChangePasswordForm />
        </section>

        <Link
          href="/favourites"
          className="mb-4 block rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 text-sm font-medium text-white backdrop-blur-md hover:bg-white/[0.05]"
        >
          Manage favourite teams, competitions &amp; matches →
        </Link>

        <Link
          href="/premium"
          className="mb-4 block rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 text-sm font-medium text-white backdrop-blur-md hover:bg-white/[0.05]"
        >
          Premium &amp; subscription →
        </Link>

        <Link
          href="/settings/notifications"
          className="mb-4 block rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 text-sm font-medium text-white backdrop-blur-md hover:bg-white/[0.05]"
        >
          Notification settings →
        </Link>

        {user.role === "user" && <PrivacyData />}
      </div>
    </main>
  )
}
