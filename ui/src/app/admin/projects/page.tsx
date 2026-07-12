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

const statusClass: Record<string, string> = {
  Ready: "bg-green-500/15 text-green-600 dark:text-green-400",
  Failed: "bg-red-500/15 text-red-600 dark:text-red-400",
};

export default async function AdminProjectsPage() {
  const session = await auth();
  if (!(session as { accessToken?: string })?.accessToken) redirect("/login");

  const projects = await getGlobalProjects((session as { accessToken?: string }).accessToken as string);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 mb-8">
        <div className="p-3 bg-brand/10 rounded-xl">
          <FolderGit2 className="w-6 h-6 text-brand" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-text-primary tracking-tight">Global Projects</h1>
          <p className="text-text-secondary mt-1">Monitor all tenant deployments across the platform.</p>
        </div>
      </div>

      <div className="rounded-xl border border-canvas-border overflow-hidden">
        <table className="w-full text-left text-sm text-text-secondary">
          <thead className="bg-canvas-border/20 text-xs uppercase font-semibold text-text-secondary">
            <tr>
              <th className="px-6 py-4">Project</th>
              <th className="px-6 py-4">Namespace</th>
              <th className="px-6 py-4">Owner Email</th>
              <th className="px-6 py-4">Status</th>
              <th className="px-6 py-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-canvas-border">
            {projects.map((p: any) => (
              <tr key={p.id} className="hover:bg-canvas-border/10 transition-colors">
                <td className="px-6 py-4 font-medium text-text-primary">{p.name}</td>
                <td className="px-6 py-4 font-mono text-xs">{p.namespace}</td>
                <td className="px-6 py-4 font-mono text-xs text-brand">{p.owner_email || p.owner_id}</td>
                <td className="px-6 py-4">
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                    statusClass[p.status] ?? "bg-yellow-500/15 text-yellow-600 dark:text-yellow-400"
                  }`}>
                    {p.status}
                  </span>
                </td>
                <td className="px-6 py-4 text-right">
                  <Link
                    href={`/projects/${p.id}`}
                    className="text-xs px-3 py-1.5 rounded-lg bg-brand text-canvas-bg hover:opacity-80 transition-opacity"
                  >
                    View
                  </Link>
                </td>
              </tr>
            ))}
            {projects.length === 0 && (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center text-text-secondary">No projects found.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
