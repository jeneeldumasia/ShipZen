import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { Server } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import Link from "next/link";

async function getGlobalDeployments(token: string) {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/admin/deployments`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store"
  });
  if (!res.ok) return [];
  return res.json();
}

export default async function AdminDeploymentsPage() {
  const session = await auth();
  if (!(session as { accessToken?: string })?.accessToken) redirect("/login");

  const deployments = await getGlobalDeployments((session as { accessToken?: string }).accessToken as string);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 mb-8">
        <div className="p-3 bg-brand/20 rounded-xl shadow-glow">
          <Server className="w-6 h-6 text-brand" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Global Deployments</h1>
          <p className="text-zinc-400 mt-1">Monitor all workloads currently running across the cluster.</p>
        </div>
      </div>

      <div className="rounded-xl border border-white/10 bg-black/40 overflow-hidden backdrop-blur-xl shadow-2xl">
        <table className="w-full text-left text-sm text-zinc-400">
          <thead className="bg-white/5 text-xs uppercase font-semibold text-zinc-300">
            <tr>
              <th className="px-6 py-4">Repo / Deployment ID</th>
              <th className="px-6 py-4">Project</th>
              <th className="px-6 py-4">Owner Email</th>
              <th className="px-6 py-4">State</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/10">
            {deployments.map((d: any) => (
              <tr key={d.deployment_id} className="hover:bg-white/5 transition-colors">
                <td className="px-6 py-4">
                  <div className="font-medium text-white truncate max-w-[200px]" title={d.repo_url}>
                    {d.repo_url.replace("https://github.com/", "")}
                  </div>
                  <div className="font-mono text-[10px] text-zinc-500 mt-1">{d.deployment_id.substring(0, 8)}</div>
                </td>
                <td className="px-6 py-4">
                  <div className="text-white">{d.project_name}</div>
                  <div className="font-mono text-xs text-zinc-500">{d.project_namespace}</div>
                </td>
                <td className="px-6 py-4 font-mono text-xs text-brand/80">{d.owner_email || "Unknown"}</td>
                <td className="px-6 py-4">
                  <StatusBadge status={d.state} error={d.last_error} />
                </td>
              </tr>
            ))}
            {deployments.length === 0 && (
              <tr>
                <td colSpan={4} className="px-6 py-8 text-center text-zinc-500">No deployments found.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
