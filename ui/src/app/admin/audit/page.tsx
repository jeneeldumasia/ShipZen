import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { Zap, Clock } from "lucide-react";
import { getBaseUrl } from "@/lib/api";

async function getAuditLogs(token: string) {
  const res = await fetch(`${getBaseUrl()}/admin/audit-logs`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store"
  });
  if (!res.ok) return [];
  return res.json();
}

export default async function AdminAuditPage() {
  const session = await auth();
  if (!(session as { accessToken?: string })?.accessToken) redirect("/login");

  const logs = await getAuditLogs((session as { accessToken?: string }).accessToken as string);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 mb-8">
        <div className="p-3 bg-brand/20 rounded-xl shadow-glow">
          <Zap className="w-6 h-6 text-brand" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-text-primary tracking-tight">Global Audit Logs</h1>
          <p className="text-text-secondary mt-1">Platform-wide security and action timeline.</p>
        </div>
      </div>

      <div className="rounded-xl border border-canvas-border bg-canvas-bg/40 overflow-hidden backdrop-blur-xl shadow-2xl">
        <table className="w-full text-left text-sm text-text-secondary">
          <thead className="bg-canvas-border/50 text-xs uppercase font-semibold text-text-primary">
            <tr>
              <th className="px-6 py-4">Timestamp</th>
              <th className="px-6 py-4">User</th>
              <th className="px-6 py-4">Action</th>
              <th className="px-6 py-4">Resource</th>
              <th className="px-6 py-4">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-canvas-border">
            {logs.map((log: any) => (
              <tr key={log.id} className="hover:bg-canvas-border/50 transition-colors">
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center gap-2 text-xs">
                    <Clock size={12} className="text-text-secondary" />
                    {new Date(log.timestamp).toLocaleString()}
                  </div>
                </td>
                <td className="px-6 py-4 font-mono text-xs">{log.user_id}</td>
                <td className="px-6 py-4">
                  <span className="px-2 py-1 bg-canvas-border rounded-md text-xs font-semibold text-text-primary">
                    {log.action}
                  </span>
                </td>
                <td className="px-6 py-4 text-xs">
                  <span className="text-brand/80">{log.resource_type}</span>: <span className="font-mono text-text-primary">{log.resource_id}</span>
                </td>
                <td className="px-6 py-4 font-mono text-xs max-w-xs truncate" title={JSON.stringify(log.details)}>
                  {JSON.stringify(log.details)}
                </td>
              </tr>
            ))}
            {logs.length === 0 && (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center">No audit logs found.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
