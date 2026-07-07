"use client";

import { useState } from "react";
import { RefreshCw, ServerCrash } from "lucide-react";
import { api } from "@/lib/api";

export function SystemControls() {
  const [loading, setLoading] = useState(false);

  const handleRestart = async () => {
    if (!window.confirm("Are you sure you want to restart the ShipZen system pods? This will cause a brief disruption.")) return;
    
    try {
      setLoading(true);
      await api.admin.restartSystem();
      alert("System pods are restarting. They will be back online shortly.");
    } catch (err: any) {
      alert(err.message || "Failed to restart system pods");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card p-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-text-primary mb-1 flex items-center gap-2">
            <ServerCrash size={18} className="text-brand" />
            System Operations
          </h2>
          <p className="text-sm text-text-secondary mb-4">
            Perform administrative operations on the ShipZen cluster. Restarting system pods will gracefully terminate the API and Worker deployments and spin up new ones.
          </p>
        </div>
        <button
          onClick={handleRestart}
          disabled={loading}
          className="btn-primary flex items-center gap-2 px-4 py-2"
        >
          {loading ? (
            <RefreshCw size={16} className="animate-spin" />
          ) : (
            <RefreshCw size={16} />
          )}
          {loading ? "Restarting..." : "Restart System Pods"}
        </button>
      </div>
    </div>
  );
}
