"use client"

import { Search } from "lucide-react"
import { useEffect, useState } from "react"

export function LivescoreHeader({ liveCount }: { liveCount: number }) {
  const [clock, setClock] = useState("")

  useEffect(() => {
    const tick = () =>
      setClock(
        new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }),
      )
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <header className="sticky top-0 z-20 border-b border-white/[0.08] bg-[#070b09]/70 backdrop-blur-xl">
      <div className="mx-auto flex max-w-2xl items-center gap-3 px-4 py-3.5">
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-emerald-400 text-lg font-black text-[#070b09] shadow-lg shadow-emerald-500/30">
            L
          </span>
          <div className="leading-tight">
            <p className="text-[15px] font-bold tracking-tight text-white">
              Live<span className="text-emerald-400">Pitch</span>
            </p>
            <p className="flex items-center gap-1.5 text-[11px] text-white/40">
              <span className="ls-live-dot h-1.5 w-1.5 rounded-full bg-emerald-400" />
              {liveCount} matches live · {clock || "--:--"}
            </p>
          </div>
        </div>

        <button
          type="button"
          aria-label="Search matches"
          className="ml-auto grid h-9 w-9 place-items-center rounded-xl border border-white/10 bg-white/[0.03] text-white/60 transition-colors hover:bg-white/[0.06] hover:text-white"
        >
          <Search className="h-4 w-4" />
        </button>
      </div>
    </header>
  )
}
