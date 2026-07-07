"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw, Play } from "lucide-react";
import { api } from "@/lib/api";

export function RestartAppButton({
  projectId,
  deploymentId,
}: {
  projectId: string;
  deploymentId: string;
}) {
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleRestart = async () => {
    try {
      setLoading(true);
      await api.deployments.restart(projectId, deploymentId);
      router.refresh();
    } catch (err: any) {
      alert(err.message || "Failed to restart deployment");
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      onClick={handleRestart}
      disabled={loading}
      className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1.5"
    >
      {loading ? (
        <RefreshCw size={14} className="animate-spin text-text-secondary" />
      ) : (
        <Play size={14} className="text-text-secondary" />
      )}
      {loading ? "Restarting..." : "Restart App"}
    </button>
  );
}
