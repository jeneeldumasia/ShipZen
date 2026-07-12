import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { Server } from "lucide-react";
import Link from "next/link";

async function getGlobalDeployments(token: string) {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/admin/deployments`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store"
  });
  if (!res.ok) return [];
  return res.json();
}

const stateClass: Record<string, string> = {
  Running: "bg-green-500/15 text-green-600 dark:text-green-400",
  Failed:  "bg-red-500/15 text-red-600 dark:text-red-400",
  Queued:  "bg-yellow-500/15 text-yellow-600 dark:text-yellow-400",
  Building:"bg-blue-500/15 text-blue-600 dark:text-blue-400",
};

export default async function AdminDeploymentsPage() {
  const session = await auth();
  if (!(session as { accessToken?: string })?.accessToken) redirect("/login");

  const deployments = await getGlobalDeployments((session as { accessToken?: string }).accessToken as string);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 mb-8">
        <div className="p-3 bg-brand/10 rounded-xl">
          <Server className="w-6 h-6 text-brand" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-text-primary tracking-tight">Global Deployments</h1>
          <p className="text-text-secondary mt-1">Monitor all workloads currently running across the cluster.</p>
        </div>
      </div>

      <div className="rounded-xl border border-canvas-border overflow-hidden">
        <table className="w-full text-left text-sm text-text-secondary">
          <thead className="bg-canvas-border/20 text-xs uppercase font-semibold text-text-secondary">
            <tr>
              <th className="px-6 py-4">Repo / ID</th>
              <th className="px-6 py-4">Project</th>
              <th className="px-6 py-4">Owner</th>
              <th className="px-6 py-4">State</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-canvas-border">
            {deployments.map((d: any) => (
              <tr key={d.deployment_id} className="hover:bg-canvas-border/10 transition-colors">
                <td className="px-6 py-4">
                  <div className="font-medium text-text-primary truncate max-w-[200px]" title={d.repo_url}>
                    {d.repo_url.replace("https://github.com/", "")}
                  </div>
                  <div className="font-mono text-[10px] text-text-secondary mt-1">{d.deployment_id.substring(0, 8)}…</div>
                </td>
                <td className="px-6 py-4">
                  <div className="text-text-primary">{d.project_name}</div>
                  <div className="font-mono text-xs text-text-secondary">{d.project_namespace}</div>
                </td>
                <td className="px-6 py-4 font-mono text-xs text-brand">{d.owner_email || "Unknown"}</td>
                <td className="px-6 py-4">
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                    stateClass[d.state] ?? "bg-canvas-border/30 text-text-secondary"
                  }`}>
                    {d.state}
                  </span>
                  {d.state === "Failed" && d.last_error && (
                    <div className="text-xs text-red-500 mt-1 truncate max-w-[200px]" title={d.last_error}>
                      {d.last_error}
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {deployments.length === 0 && (
              <tr>
                <td colSpan={4} className="px-6 py-8 text-center text-text-secondary">No deployments found.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
