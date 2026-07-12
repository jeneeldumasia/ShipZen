"use client";

import { useEffect, useRef, useState } from "react";
import { Terminal, Wifi, WifiOff } from "lucide-react";

const ANSI_RE = /[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g;

interface Props {
  projectId: string;
  deploymentId: string;
  token?: string;
}

/**
 * Inline live-log terminal shown on the deployment page while a build is active.
 * Connects directly to the WS log endpoint and streams output in real-time.
 * Automatically stops when the server closes the connection (build finished).
 */
export function LiveLogPanel({ projectId, deploymentId, token }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [ended, setEnded] = useState(false);
  const scrollRef = useRef<HTMLPreElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!token) return;

    const wsUrl = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
      .replace(/^http/, "ws");

    const ws = new WebSocket(
      `${wsUrl}/ws/projects/${projectId}/deployments/${deploymentId}/logs?token=${token}`
    );
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (e: MessageEvent) => {
      const line = (e.data as string).replace(ANSI_RE, "");
      setLines((prev) => [...prev, line]);
    };

    ws.onerror = () => {
      setLines((prev) => [...prev, "\n[connection error]"]);
      setConnected(false);
      setEnded(true);
    };

    ws.onclose = () => {
      setConnected(false);
      setEnded(true);
    };

    return () => {
      ws.close();
    };
  }, [projectId, deploymentId, token]);

  // Auto-scroll to bottom on new lines
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div className="w-full flex flex-col items-center justify-center relative">
      <div className="h-64 w-full flex flex-col items-center justify-end overflow-hidden pb-4 relative" style={{ maskImage: "linear-gradient(to bottom, transparent, black 80%)", WebkitMaskImage: "linear-gradient(to bottom, transparent, black 80%)" }}>
        
        {lines.length === 0 && !ended ? (
          <div className="flex items-center gap-3 text-text-secondary font-mono text-xs uppercase tracking-widest animate-pulse">
            <Wifi size={14} className="text-brand" />
            Awaiting Telemetry...
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 w-full max-w-2xl text-center">
            {lines.slice(-6).map((line, idx, arr) => {
              // The very last item is fully opaque. As we go back, they fade.
              const isLast = idx === arr.length - 1;
              const opacity = isLast ? 1 : Math.max(0.1, (idx + 1) / arr.length);
              
              return (
                <div 
                  key={line + idx} 
                  className={`font-mono text-xs tracking-widest uppercase transition-all duration-500 ease-out`}
                  style={{ 
                    opacity: opacity, 
                    transform: `translateY(${isLast ? '0px' : '-4px'}) scale(${isLast ? 1 : 0.98})`,
                    color: isLast ? "var(--text-primary)" : "var(--text-secondary)"
                  }}
                >
                  {line.substring(0, 80)}{line.length > 80 ? "..." : ""}
                </div>
              );
            })}
            
            {connected && (
              <div className="mt-2 text-[10px] font-mono text-brand uppercase tracking-widest animate-pulse flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-brand" /> Streaming
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
