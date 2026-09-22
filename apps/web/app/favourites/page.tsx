import { redirect } from "next/navigation"
import Link from "next/link"

import { AnimatedBackground } from "@/components/animated-background"
import { FavouritesList } from "@/components/favourites-list"
import { getServerFavourites, getServerUser } from "@/lib/server-auth"

export const dynamic = "force-dynamic"

export default async function FavouritesPage() {
  const user = await getServerUser()
  if (!user) redirect("/login")

  const favourites = (await getServerFavourites()) ?? { teams: [], competitions: [], matches: [] }

  return (
    <main className="relative min-h-screen text-white">
      <AnimatedBackground />
      <div className="mx-auto max-w-2xl px-4 pb-16 pt-6">
        <Link href="/" className="text-xs text-white/50 hover:text-white/80">
          ← Back to livescores
        </Link>
        <h1 className="mt-4 mb-4 text-lg font-bold text-white">Your favourites</h1>
        <FavouritesList initial={favourites} />
      </div>
    </main>
  )
}
