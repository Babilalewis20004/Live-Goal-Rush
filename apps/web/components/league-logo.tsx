import Image from "next/image"
import { shouldOptimizeCrest } from "@/lib/images"
import { colorsFor } from "@/lib/colors"

/** Small shield emblem generated from a competition's name. */
export function LeagueLogo({
  name,
  logoUrl,
  size = 26,
}: {
  name: string
  logoUrl?: string | null
  size?: number
}) {
  if (logoUrl) {
    return (
      <Image
        src={logoUrl}
        alt={`${name} emblem`}
        width={size}
        height={size}
        unoptimized={!shouldOptimizeCrest(logoUrl)}
        className="shrink-0 object-contain"
      />
    )
  }

  const { color } = colorsFor(name)
  const gradId = `league-grad-${name.replace(/\s+/g, "")}`

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 36"
      role="img"
      aria-label={`${name} emblem`}
      className="shrink-0"
      style={{ filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.4))" }}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} />
          <stop offset="100%" stopColor={color} stopOpacity="0.65" />
        </linearGradient>
      </defs>

      <path
        d="M16 1 L30 5 V17 C30 26 24 32 16 35 C8 32 2 26 2 17 V5 Z"
        fill={`url(#${gradId})`}
        stroke="rgba(255,255,255,0.35)"
        strokeWidth="1.5"
      />
      <path d="M16 1 L30 5 V9 L16 6 L2 9 V5 Z" fill="rgba(255,255,255,0.18)" />
      <path
        d="M16 12 L18 17 L23.5 17.3 L19.2 20.7 L20.7 26 L16 22.9 L11.3 26 L12.8 20.7 L8.5 17.3 L14 17 Z"
        fill="rgba(255,255,255,0.92)"
      />
    </svg>
  )
}
