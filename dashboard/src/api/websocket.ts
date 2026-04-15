/* WebSocket manager with auto-reconnect + React hook */

import { useEffect, useRef, useCallback } from "react";
import type { WsEvent } from "../types/api";

type WsHandler = (event: WsEvent) => void;

class WebSocketManager {
  private ws: WebSocket | null = null;
  private listeners = new Set<WsHandler>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private url: string;

  constructor() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.url = `${proto}://${location.host}/ws`;
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      console.log("[ws] connected");
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
    };

    this.ws.onmessage = (e) => {
      try {
        const event: WsEvent = JSON.parse(e.data);
        this.listeners.forEach((fn) => fn(event));
      } catch {
        /* ignore non-JSON frames */
      }
    };

    this.ws.onclose = () => {
      console.log("[ws] disconnected — reconnecting in 3s");
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, 3000);
  }

  subscribe(fn: WsHandler) {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  send(data: Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }
}

export const wsManager = new WebSocketManager();

/** React hook — subscribe to WebSocket events. */
export function useWebSocket(handler: WsHandler) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  const stableHandler = useCallback((e: WsEvent) => handlerRef.current(e), []);

  useEffect(() => {
    wsManager.connect();
    return wsManager.subscribe(stableHandler);
  }, [stableHandler]);
}
