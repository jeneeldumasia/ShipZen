"use client";

import { useState, useEffect, useRef } from "react";
import { Terminal, X, ExternalLink } from "lucide-react";

export function LogViewer({ projectId, deploymentId, buildId }: { projectId: string; deploymentId: string; buildId: string }) {
  const [open, setOpen] = useState(false);
  const [logs, setLogs] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (open) {
      setLoading(true);
      setLogs("");
      // Fetch the presigned URL
      fetch(`/api/proxy/projects/${projectId}/deployments/${deploymentId}/builds/${buildId}/logs`)
        .then(res => res.json())
        .then(data => {
          if (data.url) {
            return fetch(data.url);
          }
          throw new Error(data.message || "No URL returned");
        })
        .then(res => res.text())
        .then(text => {
          // Strip ANSI escape codes
          const cleanText = text.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
          setLogs(cleanText);
        })
        .catch(err => {
          setLogs(`Error loading logs: ${err.message}`);
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [open, projectId, deploymentId, buildId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="text-xs text-brand hover:underline flex items-center gap-1"
      >
        <Terminal size={12} />
        View Logs
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm">
          <div className="w-[800px] max-w-full bg-zinc-950 border-l border-zinc-800 shadow-2xl flex flex-col animate-in slide-in-from-right duration-300">
            <div className="flex items-center justify-between p-4 border-b border-zinc-800 bg-zinc-900/50">
              <div className="flex items-center gap-2 text-zinc-100">
                <Terminal size={16} className="text-brand" />
                <h3 className="font-semibold text-sm font-mono">Build Logs</h3>
                <span className="text-xs text-text-secondary font-mono ml-2">{buildId.slice(0, 8)}</span>
              </div>
              <button onClick={() => setOpen(false)} className="text-text-secondary hover:text-white transition-colors">
                <X size={18} />
              </button>
            </div>
            
            <div className="flex-1 p-4 overflow-hidden relative">
              {loading ? (
                <div className="absolute inset-0 flex items-center justify-center text-brand font-mono text-sm animate-pulse">
                  Fetching logs from S3...
                </div>
              ) : (
                <pre ref={scrollRef} className="h-full overflow-y-auto text-[11px] font-mono leading-relaxed text-zinc-300 whitespace-pre-wrap font-medium">
                  {logs || "No logs available."}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
