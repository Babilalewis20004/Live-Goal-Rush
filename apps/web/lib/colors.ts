/** Deterministic team/competition crest colors, derived from name.
 *
 * The API deliberately doesn't return brand colors (neither the mock data
 * nor most real football-data providers reliably supply them), so crests
 * are generated client-side from a fixed palette instead. Same name always
 * maps to the same colors.
 */

const PALETTE: readonly [string, string][] = [
  ["#1e40af", "#facc15"],
  ["#7c3aed", "#f472b6"],
  ["#dc2626", "#f8fafc"],
  ["#0ea5e9", "#0f172a"],
  ["#059669", "#bbf7d0"],
  ["#ea580c", "#1e293b"],
  ["#0891b2", "#f1f5f9"],
  ["#be123c", "#fde68a"],
  ["#4338ca", "#a5f3fc"],
  ["#15803d", "#f8fafc"],
]

function hashString(value: string): number {
  let hash = 0
  for (let i = 0; i < value.length; i++) {
    hash = (hash * 31 + value.charCodeAt(i)) >>> 0
  }
  return hash
}

export function colorsFor(name: string): { color: string; accent: string } {
  const [color, accent] = PALETTE[hashString(name) % PALETTE.length]
  return { color, accent }
}

export function shortCodeFor(name: string, shortName?: string | null): string {
  if (shortName) return shortName.slice(0, 3).toUpperCase()
  const words = name.split(/\s+/).filter(Boolean)
  if (words.length === 1) return words[0].slice(0, 3).toUpperCase()
  return words
    .map((w) => w[0])
    .join("")
    .slice(0, 3)
    .toUpperCase()
}
