import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

// apps/mobile/src/lib/match-centre.ts is a hand-maintained copy of this app's
// lib/match-centre.ts (there is no shared-package build step, same as the API
// types). This test fails loudly if the two drift, since the web suite is the
// one that actually exercises the logic.
const here = import.meta.dirname

function body(file: string): string {
  const source = readFileSync(file, "utf8").replace(/\r\n/g, "\n")
  // everything from the first import onwards; the leading comment differs on purpose
  return source.slice(source.indexOf("import type"))
}

describe("match-centre logic copies", () => {
  it("web and mobile copies are identical", () => {
    const web = body(path.join(here, "match-centre.ts"))
    const mobile = body(path.join(here, "../../mobile/src/lib/match-centre.ts"))
    expect(mobile).toBe(web)
  })

  it("both apps' API type files declare the same Phase 4 contract", () => {
    const phase4 = (file: string) => {
      const source = readFileSync(file, "utf8").replace(/\r\n/g, "\n")
      return source.slice(source.indexOf("// -- Phase 4"))
    }
    const web = phase4(path.join(here, "../types/api.ts"))
    expect(phase4(path.join(here, "../../mobile/src/types/api.ts"))).toBe(web)
    expect(phase4(path.join(here, "../../../packages/shared/types.ts"))).toBe(web)
  })
})
