"use client"

import { Search, X } from "lucide-react"
import { useRouter } from "next/navigation"
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react"

import { useRecentSearches } from "@/hooks/use-recent-searches"
import { api } from "@/lib/api"
import { normalizeSearch } from "@/lib/search-history"
import type { SearchSuggestion } from "@/types/api"

const TYPE_LABEL: Record<SearchSuggestion["type"], string> = {
  team: "Team",
  player: "Player",
  competition: "Competition",
  article: "News",
}

export function suggestionHref(s: SearchSuggestion): string {
  switch (s.type) {
    case "team":
      return `/team/${s.id}`
    case "player":
      return `/player/${s.id}`
    case "competition":
      return `/competition/${s.id}`
    default:
      return `/article/${s.slug}`
  }
}

/** Search field with suggestions, built as an ARIA 1.2 combobox: the input
 * keeps focus while Up/Down move a highlighted option (announced through
 * `aria-activedescendant`), Enter opens it, Escape closes. With nothing typed
 * it offers the viewer's own recent searches. */
export function SearchBox({ initialQuery = "", autoFocus = false }: { initialQuery?: string; autoFocus?: boolean }) {
  const router = useRouter()
  const listId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [value, setValue] = useState(initialQuery)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([])
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const { recent, remember, forget, forgetAll } = useRecentSearches()

  const trimmed = normalizeSearch(value)
  const showRecent = open && trimmed.length === 0 && recent.length > 0
  const showSuggestions = open && trimmed.length >= 2

  useEffect(() => {
    if (trimmed.length < 2) return
    let stale = false
    const handle = setTimeout(async () => {
      setLoading(true)
      try {
        const result = await api.getSearchSuggestions(trimmed)
        if (stale) return
        setSuggestions(result.suggestions)
        setFailed(false)
        setActive(-1)
      } catch {
        if (!stale) setFailed(true)
      } finally {
        if (!stale) setLoading(false)
      }
    }, 200)
    return () => {
      stale = true
      clearTimeout(handle)
    }
  }, [trimmed])

  function submit(query: string) {
    const clean = normalizeSearch(query)
    if (!clean) return
    remember(clean)
    setOpen(false)
    router.push(`/search?q=${encodeURIComponent(clean)}`)
  }

  function choose(s: SearchSuggestion) {
    remember(trimmed || s.label)
    api.trackSearch(trimmed || s.label, s.type, s.id).catch(() => {})
    setOpen(false)
    router.push(suggestionHref(s))
  }

  const options = showSuggestions ? suggestions.length : showRecent ? recent.length : 0

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" && options > 0) {
      event.preventDefault()
      setOpen(true)
      setActive((i) => (i + 1) % options)
    } else if (event.key === "ArrowUp" && options > 0) {
      event.preventDefault()
      setActive((i) => (i <= 0 ? options - 1 : i - 1))
    } else if (event.key === "Escape") {
      setOpen(false)
      setActive(-1)
    } else if (event.key === "Enter") {
      event.preventDefault()
      if (active >= 0 && showSuggestions && suggestions[active]) choose(suggestions[active])
      else if (active >= 0 && showRecent && recent[active]) submit(recent[active])
      else submit(value)
    }
  }

  const optionId = (i: number) => `${listId}-opt-${i}`

  return (
    <div className="relative">
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault()
          submit(value)
        }}
        className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-1 focus-within:border-emerald-400/60 focus-within:ring-2 focus-within:ring-emerald-400/30"
      >
        <Search className="h-4 w-4 shrink-0 text-white/40" aria-hidden />
        <label htmlFor={`${listId}-input`} className="sr-only">
          Search teams, players, competitions, matches and news
        </label>
        <input
          id={`${listId}-input`}
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded={showSuggestions || showRecent}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? optionId(active) : undefined}
          autoComplete="off"
          autoFocus={autoFocus}
          maxLength={100}
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            setOpen(true)
            setActive(-1)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={onKeyDown}
          placeholder="Search teams, players, competitions, news…"
          className="min-h-10 w-full bg-transparent text-sm text-white placeholder:text-white/30 focus:outline-none [&::-webkit-search-cancel-button]:hidden"
        />
        {value && (
          <button
            type="button"
            aria-label="Clear search"
            onClick={() => {
              setValue("")
              setSuggestions([])
              setActive(-1)
              inputRef.current?.focus()
            }}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-white/50 hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-emerald-400"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        )}
      </form>

      <div role="status" aria-live="polite" className="sr-only">
        {showSuggestions && !loading && !failed ? `${suggestions.length} suggestions` : ""}
      </div>

      {(showSuggestions || showRecent) && (
        <ul
          id={listId}
          role="listbox"
          aria-label={showSuggestions ? "Suggestions" : "Recent searches"}
          className="absolute left-0 right-0 z-30 mt-1 max-h-80 overflow-auto rounded-xl border border-white/10 bg-[#0b100d] py-1 shadow-xl"
        >
          {showSuggestions && loading && suggestions.length === 0 && (
            <li role="presentation" className="px-3 py-2 text-xs text-white/40">
              Searching…
            </li>
          )}
          {showSuggestions && failed && (
            <li role="presentation" className="px-3 py-2 text-xs text-red-300">
              Suggestions are unavailable — press Enter to search.
            </li>
          )}
          {showSuggestions && !loading && !failed && suggestions.length === 0 && (
            <li role="presentation" className="px-3 py-2 text-xs text-white/40">
              No suggestions — press Enter to search for &ldquo;{trimmed}&rdquo;.
            </li>
          )}
          {showSuggestions &&
            suggestions.map((s, i) => (
              <li
                key={`${s.type}-${s.id}`}
                id={optionId(i)}
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(s)}
                className={`flex cursor-pointer items-center justify-between gap-3 px-3 py-2.5 text-sm ${i === active ? "bg-white/[0.1]" : "hover:bg-white/[0.06]"}`}
              >
                <span className="truncate text-white">{s.label}</span>
                <span className="shrink-0 text-[10px] uppercase tracking-wide text-white/40">{TYPE_LABEL[s.type]}</span>
              </li>
            ))}
          {showRecent && (
            <>
              <li role="presentation" className="flex items-center justify-between px-3 pb-1 pt-2 text-[10px] uppercase tracking-wide text-white/40">
                <span>Recent searches</span>
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={forgetAll}
                  className="rounded px-1 normal-case text-white/50 hover:text-white focus-visible:outline-2 focus-visible:outline-emerald-400"
                >
                  Clear all
                </button>
              </li>
              {recent.map((q, i) => (
                <li
                  key={q}
                  id={optionId(i)}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => submit(q)}
                  className={`flex cursor-pointer items-center justify-between gap-3 px-3 py-2.5 text-sm ${i === active ? "bg-white/[0.1]" : "hover:bg-white/[0.06]"}`}
                >
                  <span className="truncate text-white/80">{q}</span>
                  <button
                    type="button"
                    aria-label={`Remove ${q} from recent searches`}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={(e) => {
                      e.stopPropagation()
                      forget(q)
                    }}
                    className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-white/40 hover:bg-white/[0.08] hover:text-white focus-visible:outline-2 focus-visible:outline-emerald-400"
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </li>
              ))}
            </>
          )}
        </ul>
      )}
    </div>
  )
}
