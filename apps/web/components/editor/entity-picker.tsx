"use client"

import { useState } from "react"

import { api } from "@/lib/api"
import type { LinkedEntities } from "@/lib/editor"
import type { SearchResults } from "@/types/api"

type Kind = keyof LinkedEntities
type MatchRow = SearchResults["matches"][number]

const LABEL: Record<Kind, string> = {
  teams: "Teams",
  players: "Players",
  competitions: "Competitions",
  matches: "Matches",
}

const BTN =
  "min-h-9 rounded-lg border border-white/10 bg-white/[0.05] px-3 text-xs text-white/80 hover:bg-white/[0.1] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"

/** Links an article to existing teams, players, competitions and matches. It
 * searches the real catalogue (never creates football entities), and the
 * server rejects unknown ids, so what is chosen here is always a real row. */
export function EntityPicker({ value, onChange }: { value: LinkedEntities; onChange: (next: LinkedEntities) => void }) {
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<SearchResults | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function search() {
    const q = query.trim()
    if (q.length < 2) return
    setBusy(true)
    setError(null)
    try {
      setResults(await api.search(q))
    } catch {
      setError("Search failed. Try again.")
    } finally {
      setBusy(false)
    }
  }

  function add<K extends Kind>(kind: K, item: LinkedEntities[K][number]) {
    const list = value[kind] as { id: number }[]
    if (list.some((x) => x.id === item.id)) return
    onChange({ ...value, [kind]: [...list, item] })
  }

  function remove(kind: Kind, id: number) {
    onChange({ ...value, [kind]: (value[kind] as { id: number }[]).filter((x) => x.id !== id) })
  }

  const chips: { kind: Kind; id: number; label: string }[] = [
    ...value.teams.map((t) => ({ kind: "teams" as const, id: t.id, label: t.name })),
    ...value.players.map((p) => ({ kind: "players" as const, id: p.id, label: p.name })),
    ...value.competitions.map((c) => ({ kind: "competitions" as const, id: c.id, label: c.name })),
    ...value.matches.map((m) => ({ kind: "matches" as const, id: m.id, label: `${m.home_team.name} v ${m.away_team.name}` })),
  ]

  return (
    <fieldset className="space-y-3 rounded-2xl border border-white/[0.08] p-4">
      <legend className="px-1 text-sm font-semibold text-white">Linked football</legend>
      <p className="text-xs text-white/45">
        Link teams, players, competitions or matches this story is about. It will appear on their pages.
      </p>

      {chips.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label="Linked items">
          {chips.map((chip) => (
            <li key={`${chip.kind}-${chip.id}`} className="inline-flex items-center gap-1 rounded-full bg-white/[0.07] py-1 pl-3 pr-1 text-xs text-white">
              <span className="text-white/40">{LABEL[chip.kind].slice(0, -1)}:</span> {chip.label}
              <button
                type="button"
                aria-label={`Remove ${chip.label}`}
                onClick={() => remove(chip.kind, chip.id)}
                className="grid h-6 w-6 place-items-center rounded-full text-white/50 hover:bg-white/[0.1] hover:text-white focus-visible:outline-2 focus-visible:outline-emerald-400"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2">
        <label htmlFor="entity-search" className="sr-only">
          Search football to link
        </label>
        <input
          id="entity-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              void search()
            }
          }}
          maxLength={100}
          placeholder="Search a team, player, competition or match…"
          className="min-h-10 flex-1 rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm text-white placeholder:text-white/30 focus:border-emerald-400/60 focus:outline-none"
        />
        <button type="button" onClick={search} disabled={busy} className={BTN}>
          {busy ? "Searching…" : "Search"}
        </button>
      </div>
      {error && (
        <p role="alert" className="text-xs text-red-300">
          {error}
        </p>
      )}

      {results && (
        <div className="space-y-3" aria-live="polite">
          {(["teams", "players", "competitions", "matches"] as const).map((kind) => {
            const items = results[kind] as { id: number }[]
            if (items.length === 0) return null
            return (
              <div key={kind}>
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/40">{LABEL[kind]}</p>
                <ul className="space-y-1">
                  {items.slice(0, 5).map((item) => {
                    const label =
                      kind === "matches"
                        ? `${(item as unknown as MatchRow).home_team.name} v ${(item as unknown as MatchRow).away_team.name}`
                        : (item as unknown as { name: string }).name
                    const added = (value[kind] as { id: number }[]).some((x) => x.id === item.id)
                    return (
                      <li key={item.id} className="flex items-center justify-between gap-2 rounded-lg bg-white/[0.03] px-3 py-1.5 text-sm text-white/85">
                        <span className="truncate">{label}</span>
                        <button
                          type="button"
                          disabled={added}
                          onClick={() => add(kind, item as never)}
                          className={`${BTN} min-h-8 shrink-0 disabled:opacity-50`}
                        >
                          {added ? "Added" : "Add"}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )
          })}
          {results.teams.length + results.players.length + results.competitions.length + results.matches.length === 0 && (
            <p className="text-xs text-white/40">Nothing found for &ldquo;{query}&rdquo;.</p>
          )}
        </div>
      )}
    </fieldset>
  )
}
