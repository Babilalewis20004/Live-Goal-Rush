import { redirect } from "next/navigation"
import Link from "next/link"

import { AnimatedBackground } from "@/components/animated-background"
import { ContentNotificationSettings } from "@/components/content-notification-settings"
import { NotificationSettings } from "@/components/notification-settings"
import {
  getServerContentPreferences,
  getServerFavourites,
  getServerNotificationPreferences,
  getServerUser,
} from "@/lib/server-auth"

export const dynamic = "force-dynamic"

export default async function NotificationSettingsPage() {
  const user = await getServerUser()
  if (!user) redirect("/login")

  const [preferences, favourites, contentPreferences] = await Promise.all([
    getServerNotificationPreferences(),
    getServerFavourites(),
    getServerContentPreferences(),
  ])

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-lg px-4 pb-16 pt-10">
        <Link href="/profile" className="text-xs text-white/50 hover:text-white/80">
          ← Back to profile
        </Link>
        <h1 className="mb-6 mt-4 text-lg font-bold text-white">Notification settings</h1>
        <NotificationSettings initialPreferences={preferences} favourites={favourites} />
        <ContentNotificationSettings initial={contentPreferences} />
      </div>
    </main>
  )
}
