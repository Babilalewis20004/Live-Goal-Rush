import { afterEach, describe, expect, it } from "vitest"

import { shouldOptimizeCrest } from "./images"

describe("shouldOptimizeCrest", () => {
  afterEach(() => {
    delete process.env.NEXT_PUBLIC_CREST_IMAGE_HOSTS
  })

  it("optimises crests from the provider CDNs", () => {
    expect(shouldOptimizeCrest("https://media.api-sports.io/football/teams/33.png")).toBe(true)
    expect(shouldOptimizeCrest("https://crests.football-data.org/57.png")).toBe(true)
  })

  it("leaves SVGs alone (the optimizer refuses them and they are tiny)", () => {
    expect(shouldOptimizeCrest("https://crests.football-data.org/57.svg")).toBe(false)
    expect(shouldOptimizeCrest("https://media.api-sports.io/x.SVG?v=2")).toBe(false)
  })

  it("never asks the optimizer to fetch from a host it was not configured for (next/image would throw)", () => {
    expect(shouldOptimizeCrest("https://evil.example/crest.png")).toBe(false)
    expect(shouldOptimizeCrest("https://media.api-sports.io.evil.example/x.png")).toBe(false)
    expect(shouldOptimizeCrest("http://media.api-sports.io/x.png")).toBe(false)
    expect(shouldOptimizeCrest("/relative/crest.png")).toBe(false)
    expect(shouldOptimizeCrest(null)).toBe(false)
    expect(shouldOptimizeCrest("not a url")).toBe(false)
  })

  it("honours a configured host list", () => {
    process.env.NEXT_PUBLIC_CREST_IMAGE_HOSTS = "cdn.example.com, other.example.com"
    expect(shouldOptimizeCrest("https://cdn.example.com/a.png")).toBe(true)
    expect(shouldOptimizeCrest("https://media.api-sports.io/a.png")).toBe(false)
  })
})
