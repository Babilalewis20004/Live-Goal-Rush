import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { RealtimeConnection } from "./realtime"

class MockWebSocket {
  static instances: MockWebSocket[] = []
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 3

  readyState = MockWebSocket.CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []

  constructor(public url: string) {
    MockWebSocket.instances.push(this)
  }

  send(data: string): void {
    this.sent.push(data)
  }

  // Simulates a real transport close -- fires onclose the way a browser
  // WebSocket does, whether triggered by the server or by our own close().
  close(): void {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.()
  }

  triggerOpen(): void {
    this.readyState = MockWebSocket.OPEN
    this.onopen?.()
  }

  triggerMessage(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

beforeEach(() => {
  MockWebSocket.instances = []
  vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket)
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe("RealtimeConnection", () => {
  it("transitions connecting -> open on a successful handshake", () => {
    const statuses: string[] = []
    const connection = new RealtimeConnection({
      url: "ws://test",
      onMessage: () => {},
      onStatusChange: (s) => statuses.push(s),
    })

    connection.connect()
    expect(statuses).toEqual(["connecting"])

    MockWebSocket.instances[0].triggerOpen()
    expect(statuses).toEqual(["connecting", "open"])
  })

  it("delivers parsed messages to onMessage, ignoring PONG frames", () => {
    const messages: unknown[] = []
    const connection = new RealtimeConnection({ url: "ws://test", onMessage: (m) => messages.push(m) })
    connection.connect()
    const ws = MockWebSocket.instances[0]
    ws.triggerOpen()

    ws.triggerMessage({ type: "PONG" })
    ws.triggerMessage({ type: "MATCH_UPDATED", match: { id: "1", home_score: 1 } })

    expect(messages).toEqual([{ type: "MATCH_UPDATED", match: { id: "1", home_score: 1 } }])
  })

  it("ignores a malformed (non-JSON) frame instead of throwing", () => {
    const messages: unknown[] = []
    const connection = new RealtimeConnection({ url: "ws://test", onMessage: (m) => messages.push(m) })
    connection.connect()
    const ws = MockWebSocket.instances[0]
    ws.triggerOpen()

    expect(() => ws.onmessage?.({ data: "not json" })).not.toThrow()
    expect(messages).toEqual([])
  })

  it("sends a heartbeat ping on the configured interval while open", () => {
    const connection = new RealtimeConnection({ url: "ws://test", onMessage: () => {}, heartbeatMs: 1000 })
    connection.connect()
    const ws = MockWebSocket.instances[0]
    ws.triggerOpen()

    vi.advanceTimersByTime(1000)
    expect(ws.sent).toEqual([JSON.stringify({ type: "PING" })])

    vi.advanceTimersByTime(1000)
    expect(ws.sent).toHaveLength(2)
  })

  it("reconnects after an unexpected close, refreshing REST state first", async () => {
    const onReconnect = vi.fn().mockResolvedValue(undefined)
    const statuses: string[] = []
    const connection = new RealtimeConnection({
      url: "ws://test",
      onMessage: () => {},
      onStatusChange: (s) => statuses.push(s),
      onReconnect,
    })

    connection.connect()
    MockWebSocket.instances[0].triggerOpen()
    MockWebSocket.instances[0].close() // server-initiated -- not connection.close()

    expect(statuses.at(-1)).toBe("reconnecting")
    expect(MockWebSocket.instances).toHaveLength(1)
    expect(onReconnect).not.toHaveBeenCalled()

    // Backoff for the first attempt is jittered between 500ms-1000ms;
    // 2000ms is safely past the maximum without depending on the jitter.
    await vi.advanceTimersByTimeAsync(2000)

    expect(onReconnect).toHaveBeenCalledTimes(1)
    expect(MockWebSocket.instances).toHaveLength(2)
  })

  it("does not reconnect after an explicit close()", () => {
    const statuses: string[] = []
    const connection = new RealtimeConnection({
      url: "ws://test",
      onMessage: () => {},
      onStatusChange: (s) => statuses.push(s),
    })

    connection.connect()
    MockWebSocket.instances[0].triggerOpen()
    connection.close()

    expect(statuses.at(-1)).toBe("closed")

    vi.advanceTimersByTime(60_000)
    expect(MockWebSocket.instances).toHaveLength(1) // no reconnect attempt was made
  })
})
