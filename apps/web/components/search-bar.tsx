"use client"

import { Search } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useEffect, useState } from "react"

export function SearchBar({ placeholder = "Search teams, competitions, players…" }: { placeholder?: string }) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const [value, setValue] = useState(searchParams.get("q") ?? "")

  useEffect(() => {
    const handle = setTimeout(() => {
      const params = new URLSearchParams(searchParams)
      if (value) {
        params.set("q", value)
      } else {
        params.delete("q")
      }
      router.replace(`${pathname}?${params.toString()}`)
    }, 300)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  return (
    <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5">
      <Search className="h-4 w-4 shrink-0 text-white/40" />
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-transparent text-sm text-white placeholder:text-white/30 focus:outline-none"
      />
    </div>
  )
}
