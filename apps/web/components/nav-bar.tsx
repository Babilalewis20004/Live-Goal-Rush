"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"

import { useAuth } from "@/lib/auth-context"

export function NavBar() {
  const { user, loading, logout } = useAuth()
  const router = useRouter()

  const handleLogout = async () => {
    await logout()
    router.push("/")
    router.refresh()
  }

  return (
    <header className="relative z-10 flex items-center justify-between px-4 py-3 text-sm">
      <Link href="/" className="font-bold text-white">
        LivePitch
      </Link>

      <nav aria-label="Main" className="flex items-center gap-4">
        <Link href="/news" className="text-white/60 hover:text-white">
          News
        </Link>
        <Link href="/search" className="text-white/60 hover:text-white">
          Search
        </Link>
        <Link href="/premium" className="text-emerald-300/80 hover:text-emerald-200">
          Premium
        </Link>
        {loading ? null : user ? (
          <>
            {(user.role === "author" || user.role === "editor" || user.role === "admin") && (
              <Link href="/editor" className="text-white/60 hover:text-white">
                Editor
              </Link>
            )}
            <Link href="/favourites" className="text-white/60 hover:text-white">
              My Teams
            </Link>
            <Link href="/profile" className="text-white/60 hover:text-white">
              {user.display_name || user.email}
            </Link>
            <button
              type="button"
              onClick={handleLogout}
              className="text-white/60 hover:text-white"
            >
              Log out
            </button>
          </>
        ) : (
          <>
            <Link href="/login" className="text-white/60 hover:text-white">
              Log in
            </Link>
            <Link href="/register" className="font-medium text-white hover:text-white/80">
              Sign up
            </Link>
          </>
        )}
      </nav>
    </header>
  )
}
