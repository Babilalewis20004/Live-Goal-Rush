import { describe, expect, it } from "vitest"

import { buildCsp, generateNonce } from "./csp"

const base = { nonce: "abc123", apiUrl: "https://api.example.com/", wsUrl: "wss://api.example.com", siteUrl: "https://livepitch.example" }

describe("buildCsp", () => {
  it("only lets nonce-bearing scripts run and forbids eval in production", () => {
    const csp = buildCsp(base)
    expect(csp).toContain("script-src 'self' 'nonce-abc123' 'strict-dynamic'")
    expect(csp).not.toContain("unsafe-eval")
    expect(csp).not.toMatch(/script-src[^;]*unsafe-inline/)
  })

  it("allows eval only in development", () => {
    expect(buildCsp({ ...base, isDev: true })).toContain("'unsafe-eval'")
  })

  it("permits the API and its WebSocket, and nothing else cross-origin, for connections", () => {
    const connect = buildCsp(base).split("; ").find((d) => d.startsWith("connect-src"))
    expect(connect).toBe("connect-src 'self' https://api.example.com wss://api.example.com")
  })

  it("derives the WebSocket origin from the API origin when none is configured", () => {
    const connect = buildCsp({ nonce: "n", apiUrl: "https://api.example.com" }).split("; ").find((d) => d.startsWith("connect-src"))
    expect(connect).toContain("wss://api.example.com")
  })

  it("blocks framing, plugins and base-tag hijacking", () => {
    const csp = buildCsp(base)
    expect(csp).toContain("frame-ancestors 'none'")
    expect(csp).toContain("object-src 'none'")
    expect(csp).toContain("base-uri 'self'")
    expect(csp).toContain("form-action 'self'")
    expect(csp).toContain("upgrade-insecure-requests")
  })

  it("does not force https on a plain-http site (local Docker would lose its API calls)", () => {
    expect(buildCsp({ ...base, siteUrl: "http://localhost:3000" })).not.toContain("upgrade-insecure-requests")
    expect(buildCsp({ nonce: "n" })).not.toContain("upgrade-insecure-requests")
  })

  it("survives a missing or malformed API url", () => {
    expect(() => buildCsp({ nonce: "n", apiUrl: "not a url" })).not.toThrow()
    expect(buildCsp({ nonce: "n" })).toContain("connect-src 'self'")
  })

  it("generates a different nonce each time", () => {
    expect(generateNonce()).not.toBe(generateNonce())
  })
})
