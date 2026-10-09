import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { TeamInjuries } from "@/components/team-injuries"
import type { TeamInjuriesOut } from "@/types/api"

const render = (injuries: TeamInjuriesOut | null) => renderToStaticMarkup(createElement(TeamInjuries, { injuries }))

describe("TeamInjuries", () => {
  it("renders nothing when the request failed, the provider has no feed, or the list is empty", () => {
    expect(render(null)).toBe("")
    expect(render({ supported: false, items: [] })).toBe("")
    // An empty card would read as "no injuries", which the feed can't promise.
    expect(render({ supported: true, items: [] })).toBe("")
  })

  it("lists players with a status badge and the reason", () => {
    const html = render({
      supported: true,
      items: [
        { player_name: "J. Doku", photo_url: null, kind: "missing", reason: "Calf Injury", match_date: "2026-10-10T14:00:00Z" },
        { player_name: "N. O'Reilly", photo_url: null, kind: "doubtful", reason: null, match_date: "2026-10-10T14:00:00Z" },
      ],
    })

    expect(html).toContain("J. Doku")
    expect(html).toContain("Calf Injury")
    expect(html).toContain("Out")
    expect(html).toContain("Doubtful")
    expect(html).toContain("10 Oct")
  })
})
