import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { FolderGit2 } from "lucide-react";
import Link from "next/link";

async function getGlobalProjects(token: string) {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/projects`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store"
  });
  if (!res.ok) return [];
  return res.json();
}

export default async function AdminProjectsPage() {
  const session = await auth();
  if (!(session as { accessToken?: string })?.accessToken) redirect("/login");

  const projects = await getGlobalProjects((session as { accessToken?: string }).accessToken as string);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 mb-8">
        <div className="p-3 bg-brand/20 rounded-xl shadow-glow">
          <FolderGit2 className="w-6 h-6 text-brand" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Global Projects</h1>
          <p className="text-zinc-400 mt-1">Monitor all tenant deployments across the platform.</p>
        </div>
      </div>

      <div className="rounded-xl border border-white/10 bg-black/40 overflow-hidden backdrop-blur-xl shadow-2xl">
        <table className="w-full text-left text-sm text-zinc-400">
          <thead className="bg-white/5 text-xs uppercase font-semibold text-zinc-300">
            <tr>
              <th className="px-6 py-4">Project</th>
              <th className="px-6 py-4">Namespace</th>
              <th className="px-6 py-4">Owner ID</th>
              <th className="px-6 py-4">Status</th>
              <th className="px-6 py-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/10">
            {projects.map((p: any) => (
              <tr key={p.id} className="hover:bg-white/5 transition-colors">
                <td className="px-6 py-4 font-medium text-white">{p.name}</td>
                <td className="px-6 py-4 font-mono text-xs">{p.namespace}</td>
                <td className="px-6 py-4 font-mono text-xs text-brand/80">{p.owner_id}</td>
                <td className="px-6 py-4">
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                    p.status === "Ready" ? "bg-green-500/20 text-green-400" :
                    p.status === "Failed" ? "bg-red-500/20 text-red-400" : "bg-yellow-500/20 text-yellow-400"
                  }`}>
                    {p.status}
                  </span>
                </td>
                <td className="px-6 py-4 text-right">
                  <Link href={`/projects/${p.id}`} className="text-xs px-3 py-1.5 rounded-lg bg-brand hover:bg-brand-hover text-white transition-colors">
                    View Logs
                  </Link>
                </td>
              </tr>
            ))}
            {projects.length === 0 && (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center">No projects found.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
