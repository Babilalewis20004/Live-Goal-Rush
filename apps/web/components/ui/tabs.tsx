"use client"

import { useRef, type KeyboardEvent, type ReactNode } from "react"

export interface TabDef<T extends string> {
  id: T
  label: string
}

const tabDomId = (prefix: string, id: string) => `${prefix}-tab-${id}`
const panelDomId = (prefix: string, id: string) => `${prefix}-panel-${id}`

/** WAI-ARIA tabs: one tab stop (roving tabindex), Left/Right/Home/End move
 * focus *and* selection. Purely client-side state -- no URL change -- so
 * switching tabs never refetches or remounts the live data above it. */
export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
  idPrefix,
  label,
}: {
  tabs: TabDef<T>[]
  active: T
  onChange: (id: T) => void
  idPrefix: string
  label: string
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = tabs.findIndex((t) => t.id === active)
    let next = index
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length
    else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length
    else if (event.key === "Home") next = 0
    else if (event.key === "End") next = tabs.length - 1
    else return
    event.preventDefault()
    onChange(tabs[next].id)
    refs.current[tabs[next].id]?.focus()
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      className="flex gap-1 overflow-x-auto rounded-xl border border-white/[0.08] bg-white/[0.03] p-1"
    >
      {tabs.map((tab) => {
        const selected = tab.id === active
        return (
          <button
            key={tab.id}
            ref={(el) => {
              refs.current[tab.id] = el
            }}
            id={tabDomId(idPrefix, tab.id)}
            role="tab"
            type="button"
            aria-selected={selected}
            aria-controls={panelDomId(idPrefix, tab.id)}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={[
              "min-h-10 shrink-0 flex-1 whitespace-nowrap rounded-lg px-3 text-xs font-semibold transition-colors",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400",
              selected ? "bg-white/[0.1] text-white" : "text-white/55 hover:bg-white/[0.05] hover:text-white/80",
            ].join(" ")}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}

export function TabPanel({
  idPrefix,
  id,
  active,
  children,
}: {
  idPrefix: string
  id: string
  active: boolean
  children: ReactNode
}) {
  if (!active) return null
  return (
    <div role="tabpanel" id={panelDomId(idPrefix, id)} aria-labelledby={tabDomId(idPrefix, id)} tabIndex={0} className="mt-4 outline-none">
      {children}
    </div>
  )
}
