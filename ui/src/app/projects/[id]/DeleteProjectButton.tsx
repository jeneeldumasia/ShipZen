"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Trash2, Loader2 } from "lucide-react";
import { api } from "@/lib/api";

export function DeleteProjectButton({ projectId, projectName }: { projectId: string; projectName: string }) {
  const router  = useRouter();
  const [loading, setLoading] = useState(false);

  async function handleDelete() {
    if (!confirm(`Delete "${projectName}"?\n\nThis will terminate its Kubernetes namespace and all running workloads.`)) return;
    setLoading(true);
    try {
      await api.projects.delete(projectId);
      router.push("/");
      router.refresh();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to delete project");
      setLoading(false);
    }
  }

  return (
    <button onClick={handleDelete} disabled={loading} className="btn-danger">
      {loading ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
      Delete
    </button>
  );
}
