import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

// The mobile app keeps hand-maintained copies of this app's shared logic and
// API types (there is no shared-package build step). These tests fail loudly
// if the copies drift, since the web suite is the one that exercises the logic.
const here = import.meta.dirname

function normalize(file: string): string {
  return readFileSync(file, "utf8").replace(/\r\n/g, "\n")
}

/** Everything from the first import onwards; the leading comment differs on purpose. */
function body(file: string): string {
  const source = normalize(file)
  return source.slice(source.indexOf("import type"))
}

describe("match-centre logic copies", () => {
  it("web and mobile copies are identical", () => {
    const web = body(path.join(here, "match-centre.ts"))
    const mobile = body(path.join(here, "../../mobile/src/lib/match-centre.ts"))
    expect(mobile).toBe(web)
  })

  it("the Phase 5 logic modules are identical on web and mobile", () => {
    for (const file of ["notification-overrides.ts", "seasons.ts"]) {
      expect(body(path.join(here, "../../mobile/src/lib", file))).toBe(body(path.join(here, file)))
    }
  })

  it("the season hook differs only by web's use-client directive", () => {
    const strip = (file: string) => normalize(file).replace('"use client"\n\n', "")
    expect(strip(path.join(here, "../../mobile/src/hooks/use-season-view.ts"))).toBe(
      strip(path.join(here, "../hooks/use-season-view.ts")),
    )
  })

  it("both apps' API type files declare the same Phase 4+ contract", () => {
    const phase4 = (file: string) => {
      const source = normalize(file)
      return source.slice(source.indexOf("// -- Phase 4"))
    }
    const web = phase4(path.join(here, "../types/api.ts"))
    expect(phase4(path.join(here, "../../mobile/src/types/api.ts"))).toBe(web)
    expect(phase4(path.join(here, "../../../packages/shared/types.ts"))).toBe(web)
  })
})
