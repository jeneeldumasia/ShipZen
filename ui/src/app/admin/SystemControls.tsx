"use client";

import { useState } from "react";
import { RefreshCw, ServerCrash } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

export function SystemControls() {
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const handleRestart = async () => {
    if (!confirming) {
      setConfirming(true);
      setTimeout(() => setConfirming(false), 3000);
      return;
    }
    
    try {
      setLoading(true);
      setConfirming(false);
      await api.admin.restartSystem();
      toast.success("System pods are restarting. They will be back online shortly.");
    } catch (err: any) {
      toast.error(err.message || "Failed to restart system pods");
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
          {loading ? "Restarting..." : confirming ? "Click again to confirm" : "Restart System Pods"}
        </button>
      </div>
    </div>
  );
}
