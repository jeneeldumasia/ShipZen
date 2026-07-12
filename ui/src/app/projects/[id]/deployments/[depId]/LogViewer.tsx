"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Terminal, X, Wifi, WifiOff, Loader2 } from "lucide-react";
import { api, getWsBaseUrl } from "@/lib/api";

const ANSI_RE = /[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g;
const LIVE_STATES = new Set(["Queued", "Building"]);

interface Props {
  projectId: string;
  deploymentId: string;
  /** undefined when the build hasn't recorded yet (live-only mode) */
  buildId?: string;
  deploymentState: string;
  token?: string;
}

export function LogViewer({ projectId, deploymentId, buildId, deploymentState, token }: Props) {
  const [open, setOpen] = useState(false);
  // lines is an array so we can append cheaply without re-scanning the full string
  const [lines, setLines] = useState<string[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "live" | "done" | "error">("idle");
  const scrollRef = useRef<HTMLPreElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const isLive = LIVE_STATES.has(deploymentState);

  // Auto-scroll whenever lines change
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  // Cleanup WS on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  const startLiveStream = useCallback(() => {
    if (!token) {
      setLines(["[error] No auth token available for live log stream."]);
      setStatus("error");
      return;
    }

    setStatus("live");
    setLines([]);

    const wsUrl = getWsBaseUrl();
    const ws = new WebSocket(
      `${wsUrl}/ws/projects/${projectId}/deployments/${deploymentId}/logs?token=${token}`
    );
    wsRef.current = ws;

    ws.onmessage = (e) => {
      const line = e.data.replace(ANSI_RE, "");
      setLines((prev) => [...prev, line]);
    };

    ws.onerror = () => {
      setLines((prev) => [...prev, "\n[connection error — logs may be incomplete]"]);
      setStatus("error");
    };

    ws.onclose = () => {
      // Build finished — transition to done so we know the stream ended
      setStatus((s) => (s === "live" ? "done" : s));
    };
  }, [projectId, deploymentId, token]);

  const loadStaticLogs = useCallback(() => {
    if (!buildId) {
      setLines(["[no build record yet]"]);
      setStatus("done");
      return;
    }

    setStatus("loading");
    setLines([]);

    api.builds
      .logs(projectId, deploymentId, buildId)
      .then((text) => {
        const clean = text.replace(ANSI_RE, "");
        setLines(clean ? clean.split("\n") : ["[empty log]"]);
        setStatus("done");
      })
      .catch((err: Error) => {
        setLines([`[error loading logs: ${err.message}]`]);
        setStatus("error");
      });
  }, [projectId, deploymentId, buildId]);

  // When the panel opens, choose live vs static
  const handleOpen = useCallback(() => {
    setOpen(true);
    if (isLive) {
      startLiveStream();
    } else {
      loadStaticLogs();
    }
  }, [isLive, startLiveStream, loadStaticLogs]);

  const handleClose = useCallback(() => {
    setOpen(false);
    wsRef.current?.close();
    wsRef.current = null;
    setStatus("idle");
    setLines([]);
  }, []);

  // If deployment transitions out of live states while panel is open, switch to static
  useEffect(() => {
    if (open && !isLive && status === "live") {
      wsRef.current?.close();
      wsRef.current = null;
      // Give the WS onclose a tick, then load final logs from S3
      setTimeout(loadStaticLogs, 500);
    }
  }, [open, isLive, status, loadStaticLogs]);

  const logText = lines.join("\n");
  const isEmpty = lines.length === 0;

  return (
    <>
      <button
        onClick={handleOpen}
        className="text-xs text-brand hover:underline flex items-center gap-1"
      >
        <Terminal size={12} />
        {isLive ? "Live Logs" : "View Logs"}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm">
          <div className="w-[800px] max-w-full bg-zinc-950 border-l border-zinc-800 shadow-2xl flex flex-col animate-in slide-in-from-right duration-300">

            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-zinc-800 bg-zinc-900/50 flex-shrink-0">
              <div className="flex items-center gap-2 text-zinc-100">
                <Terminal size={16} className="text-brand" />
                <h3 className="font-semibold text-sm font-mono">Build Logs</h3>

                {buildId && (
                  <span className="text-xs text-zinc-500 font-mono ml-1">
                    {buildId.slice(0, 8)}
                  </span>
                )}

                {/* Live / loading indicator */}
                {status === "live" && (
                  <span className="flex items-center gap-1 text-xs text-emerald-400 font-medium ml-2">
                    <Wifi size={11} className="animate-pulse" />
                    Live
                  </span>
                )}
                {status === "loading" && (
                  <span className="flex items-center gap-1 text-xs text-zinc-400 font-medium ml-2">
                    <Loader2 size={11} className="animate-spin" />
                    Loading…
                  </span>
                )}
                {status === "done" && (
                  <span className="flex items-center gap-1 text-xs text-zinc-500 font-medium ml-2">
                    <WifiOff size={11} />
                    Ended
                  </span>
                )}
                {status === "error" && (
                  <span className="text-xs text-red-400 font-medium ml-2">Error</span>
                )}
              </div>

              <button
                onClick={handleClose}
                className="text-zinc-500 hover:text-white transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Log body */}
            <div className="flex-1 overflow-hidden relative">
              {status === "loading" && isEmpty ? (
                <div className="absolute inset-0 flex items-center justify-center text-zinc-500 font-mono text-sm">
                  <Loader2 size={16} className="animate-spin mr-2" />
                  Fetching logs…
                </div>
              ) : status === "live" && isEmpty ? (
                <div className="absolute inset-0 flex items-center justify-center text-emerald-500/70 font-mono text-sm">
                  <Wifi size={14} className="animate-pulse mr-2" />
                  Waiting for build output…
                </div>
              ) : (
                <pre
                  ref={scrollRef}
                  className="h-full overflow-y-auto p-4 text-[11px] font-mono leading-relaxed text-zinc-300 whitespace-pre-wrap"
                >
                  {logText || "[no output]"}

                  {/* Blinking cursor while streaming */}
                  {status === "live" && (
                    <span className="inline-block w-2 h-3 bg-emerald-400 ml-0.5 animate-pulse align-text-bottom" />
                  )}
                </pre>
              )}
            </div>

          </div>
        </div>
      )}
    </>
  );
}
