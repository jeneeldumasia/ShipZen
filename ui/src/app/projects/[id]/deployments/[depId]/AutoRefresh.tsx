"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { getWsBaseUrl } from "@/lib/api";

/**
 * Connects to the WebSocket status endpoint for live updates.
 * Calls router.refresh() when the backend emits a state transition.
 * Automatically reconnects if the connection drops during long builds.
 */
export function AutoRefresh({ projectId, deploymentId, token }: { projectId: string; deploymentId: string; token?: string }) {
  const router = useRouter();
  const lastState = useRef<string | null>(null);

  useEffect(() => {
    if (!token) return;
    
    let ws: WebSocket;
    let reconnectTimer: NodeJS.Timeout;
    let isUnmounted = false;
    // Track whether we've received a terminal state so we stop reconnecting
    let done = false;

    const TERMINAL_STATES = new Set(["Running", "Failed", "DLQ"]);

    const connect = () => {
      if (done || isUnmounted) return;

      const wsUrl = getWsBaseUrl();
      ws = new WebSocket(`${wsUrl}/ws/projects/${projectId}/deployments/${deploymentId}/status`);

      ws.onopen = () => {
        ws.send(JSON.stringify({ token }));
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.state && data.state !== lastState.current) {
            lastState.current = data.state;
            // Refresh the server component to pick up the new DB state
            router.refresh();

            if (TERMINAL_STATES.has(data.state)) {
              // Reached a terminal state — no need to keep the socket open.
              done = true;
              ws?.close();
            }
          }
        } catch (e) {
          console.error("Failed to parse websocket message", e);
        }
      };

      ws.onerror = () => {
        // Let onclose handle reconnect
      };

      ws.onclose = () => {
        if (!isUnmounted && !done) {
          // Cloudflare drops idle WS after 100s. Reconnect automatically.
          reconnectTimer = setTimeout(connect, 3000);
        }
      };
    };

    connect();

    return () => {
      isUnmounted = true;
      done = true;
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [router, projectId, deploymentId, token]);

  return null;
}
