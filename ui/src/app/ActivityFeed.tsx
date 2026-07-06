"use client";

import { useEffect, useState } from "react";
import { Activity, RefreshCw } from "lucide-react";
import { api, AuditLog } from "@/lib/api";

export function ActivityFeed() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);

  async function fetchLogs() {
    try {
      const res = await api.audit.listGlobal();
      setLogs(res);
    } catch (e) {
      console.error("Failed to fetch activity feed:", e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 30000); // Poll every 30s
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="card overflow-hidden h-[600px] flex flex-col">
      <div className="flex items-center justify-between px-6 py-4 border-b border-canvas-border shrink-0">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-text-secondary" />
          <h2 className="text-sm font-semibold text-text-primary">Activity Feed</h2>
        </div>
        <button onClick={fetchLogs} className="text-text-secondary hover:text-text-primary transition-colors">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {loading && logs.length === 0 ? (
          <div className="text-sm text-text-secondary text-center py-8 animate-pulse">Loading activity...</div>
        ) : logs.length === 0 ? (
          <div className="text-sm text-text-secondary text-center py-8">No recent activity.</div>
        ) : (
          logs.map((log) => (
            <div key={log.id} className="bg-black/5 dark:bg-white/5 border border-canvas-border rounded-lg p-3 text-sm">
              <div className="flex items-start justify-between mb-2">
                <span className="font-semibold text-xs text-text-primary">{(log as unknown as Record<string, string>).project_name || log.project_id.slice(0, 8)}</span>
                <span className="text-[10px] text-text-secondary">
                  {new Date(log.timestamp).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                </span>
              </div>
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2">
                  <code className="text-[10px] font-mono bg-brand/10 text-brand px-1.5 py-0.5 rounded">{log.action}</code>
                  <span className="text-xs text-text-secondary">on <span className="font-medium text-text-primary">{log.resource_type}</span></span>
                </div>
                <div className="text-xs text-text-secondary font-mono truncate bg-black/5 dark:bg-white/5 p-1.5 rounded">
                  {JSON.stringify(log.details)}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
