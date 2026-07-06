import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { Zap, Clock } from "lucide-react";

async function getAuditLogs(token: string) {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/admin/audit-logs`, {
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
          <h1 className="text-3xl font-bold text-white tracking-tight">Global Audit Logs</h1>
          <p className="text-zinc-400 mt-1">Platform-wide security and action timeline.</p>
        </div>
      </div>

      <div className="rounded-xl border border-white/10 bg-black/40 overflow-hidden backdrop-blur-xl shadow-2xl">
        <table className="w-full text-left text-sm text-zinc-400">
          <thead className="bg-white/5 text-xs uppercase font-semibold text-zinc-300">
            <tr>
              <th className="px-6 py-4">Timestamp</th>
              <th className="px-6 py-4">User</th>
              <th className="px-6 py-4">Action</th>
              <th className="px-6 py-4">Resource</th>
              <th className="px-6 py-4">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/10">
            {logs.map((log: any) => (
              <tr key={log.id} className="hover:bg-white/5 transition-colors">
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center gap-2 text-xs">
                    <Clock size={12} className="text-zinc-500" />
                    {new Date(log.timestamp).toLocaleString()}
                  </div>
                </td>
                <td className="px-6 py-4 font-mono text-xs">{log.user_id}</td>
                <td className="px-6 py-4">
                  <span className="px-2 py-1 bg-white/10 rounded-md text-xs font-semibold text-white">
                    {log.action}
                  </span>
                </td>
                <td className="px-6 py-4 text-xs">
                  <span className="text-brand/80">{log.resource_type}</span>: <span className="font-mono text-zinc-300">{log.resource_id}</span>
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
