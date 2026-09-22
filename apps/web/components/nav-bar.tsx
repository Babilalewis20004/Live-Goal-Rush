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

      <nav className="flex items-center gap-4">
        {loading ? null : user ? (
          <>
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
