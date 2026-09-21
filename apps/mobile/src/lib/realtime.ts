import type { RealtimeMessage } from "@/types/api"

/**
 * A resilient WebSocket client (Phase 2 §18/§19): exponential backoff with
 * jitter on reconnect, a client-initiated heartbeat, and a hook for
 * refreshing REST state before resubscribing after a reconnect.
 *
 * This is a parallel implementation of `apps/web/lib/realtime.ts` for
 * React Native (same contract, React Native's global `WebSocket` instead
 * of the browser's) -- matches this repo's existing convention of
 * hand-synced-not-shared client code between web and mobile (see
 * apps/mobile/src/types/api.ts's header comment).
 */

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "closed"

export interface RealtimeConnectionOptions {
  url: string
  onMessage: (message: RealtimeMessage) => void
  onStatusChange?: (status: ConnectionStatus) => void
  /** Called before each reconnect attempt opens a new socket -- the
   * expected hook for re-fetching REST state (spec §18/§19). */
  onReconnect?: () => void | Promise<void>
  heartbeatMs?: number
}

const BASE_RECONNECT_DELAY_MS = 1_000
const MAX_RECONNECT_DELAY_MS = 30_000
const DEFAULT_HEARTBEAT_MS = 30_000

export class RealtimeConnection {
  private ws: WebSocket | null = null
  private attempt = 0
  private closedByCaller = false
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  constructor(private readonly options: RealtimeConnectionOptions) {}

  connect(): void {
    this.closedByCaller = false
    this.open()
  }

  close(): void {
    this.closedByCaller = true
    this.clearTimers()
    this.ws?.close()
    this.ws = null
  }

  private open(): void {
    this.setStatus(this.attempt === 0 ? "connecting" : "reconnecting")

    let socket: WebSocket
    try {
      socket = new WebSocket(this.options.url)
    } catch {
      this.scheduleReconnect()
      return
    }
    this.ws = socket

    socket.onopen = () => {
      this.attempt = 0
      this.setStatus("open")
      this.startHeartbeat()
    }

    socket.onmessage = (event) => {
      let parsed: unknown
      try {
        parsed = JSON.parse(event.data)
      } catch {
        return
      }
      if (!parsed || typeof parsed !== "object" || !("type" in parsed)) return
      if ((parsed as { type: string }).type === "PONG") return
      this.options.onMessage(parsed as RealtimeMessage)
    }

    socket.onclose = () => {
      this.stopHeartbeat()
      if (this.closedByCaller) {
        this.setStatus("closed")
        return
      }
      this.scheduleReconnect()
    }

    socket.onerror = () => {
      socket.close()
    }
  }

  private scheduleReconnect(): void {
    if (this.closedByCaller) return
    this.setStatus("reconnecting")

    const delay = Math.min(BASE_RECONNECT_DELAY_MS * 2 ** this.attempt, MAX_RECONNECT_DELAY_MS)
    const jitteredDelay = delay * (0.5 + Math.random() * 0.5)
    this.attempt += 1

    this.reconnectTimer = setTimeout(() => {
      void (async () => {
        if (this.closedByCaller) return
        try {
          await this.options.onReconnect?.()
        } finally {
          if (!this.closedByCaller) this.open()
        }
      })()
    }, jitteredDelay)
  }

  private startHeartbeat(): void {
    const intervalMs = this.options.heartbeatMs ?? DEFAULT_HEARTBEAT_MS
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "PING" }))
      }
    }, intervalMs)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer)
    this.heartbeatTimer = null
  }

  private clearTimers(): void {
    this.stopHeartbeat()
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
  }

  private setStatus(status: ConnectionStatus): void {
    this.options.onStatusChange?.(status)
  }
}
