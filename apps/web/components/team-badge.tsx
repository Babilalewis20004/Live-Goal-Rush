import Image from "next/image"
import { shouldOptimizeCrest } from "@/lib/images"
import { colorsFor, shortCodeFor } from "@/lib/colors"

/** Pick a readable text color for a given hex background. */
function readableText(hex: string): string {
  const h = hex.replace("#", "")
  const r = Number.parseInt(h.slice(0, 2), 16)
  const g = Number.parseInt(h.slice(2, 4), 16)
  const b = Number.parseInt(h.slice(4, 6), 16)
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
  return luminance > 0.6 ? "#0b0f0d" : "#f8fafc"
}

/** Deterministic motif index from the team's short code. */
function motifOf(short: string): number {
  let sum = 0
  for (let i = 0; i < short.length; i++) sum += short.charCodeAt(i)
  return sum % 4
}

type TeamBadgeProps = {
  name: string
  shortName?: string | null
  logoUrl?: string | null
  size?: number
}

export function TeamBadge({ name, shortName, logoUrl, size = 28 }: TeamBadgeProps) {
  if (logoUrl) {
    return (
      <Image
        src={logoUrl}
        alt={`${name} crest`}
        width={size}
        height={size}
        unoptimized={!shouldOptimizeCrest(logoUrl)}
        className="shrink-0 object-contain"
      />
    )
  }

  const short = shortCodeFor(name, shortName)
  const { color, accent } = colorsFor(name)
  const motif = motifOf(short)
  const text = readableText(color)
  const clipId = `crest-${short}-${size}`

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      role="img"
      aria-label={`${name} crest`}
      className="shrink-0"
      style={{ filter: "drop-shadow(0 1px 1px rgba(0,0,0,0.35))" }}
    >
      <defs>
        <clipPath id={clipId}>
          <circle cx="20" cy="20" r="19" />
        </clipPath>
      </defs>

      <g clipPath={`url(#${clipId})`}>
        <rect x="0" y="0" width="40" height="40" fill={color} />

        {motif === 0 && <rect x="20" y="0" width="20" height="40" fill={accent} />}
        {motif === 1 && <polygon points="0,40 14,40 40,0 26,0" fill={accent} />}
        {motif === 2 && <rect x="0" y="14" width="40" height="12" fill={accent} />}
        {motif === 3 && <rect x="0" y="20" width="40" height="20" fill={accent} />}
      </g>

      <circle cx="20" cy="20" r="19" fill="none" stroke="rgba(255,255,255,0.25)" strokeWidth="1.5" />
      <circle cx="20" cy="20" r="16.5" fill="none" stroke="rgba(0,0,0,0.15)" strokeWidth="1" />

      <text
        x="20"
        y="20"
        textAnchor="middle"
        dominantBaseline="central"
        fontSize="13"
        fontWeight="800"
        letterSpacing="-0.5"
        fill={text}
        style={{ fontFamily: "var(--font-sans, system-ui, sans-serif)" }}
      >
        {short}
      </text>
    </svg>
  )
}
