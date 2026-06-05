import Link from "next/link";
import { Plus, FolderGit2, CheckCircle2, Clock, AlertTriangle } from "lucide-react";
import { api, Project } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { MetricCard } from "@/components/MetricCard";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

export const dynamic = "force-dynamic";
export const metadata = { title: "Dashboard" };

async function getProjects(): Promise<Project[]> {
  try { return await api.projects.list(); }
  catch { return []; }
}

export default async function DashboardPage() {
  const projects = await getProjects();
  const ready       = projects.filter(p => p.status === "Ready").length;
  const provisioning = projects.filter(p => p.status === "Provisioning").length;
  const terminating  = projects.filter(p => p.status === "Terminating").length;

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Overview of your platform"
        actions={
          <Link href="/projects/new" className="btn-primary">
            <Plus size={15} />
            New Project
          </Link>
        }
      />

      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <MetricCard label="Total Projects" value={projects.length} icon={FolderGit2} />
        <MetricCard label="Running"        value={ready}          icon={CheckCircle2} color="green" />
        <MetricCard label="Provisioning"   value={provisioning}   icon={Clock}        color="blue" />
        <MetricCard label="Terminating"    value={terminating}    icon={AlertTriangle} color="amber" />
      </div>

      {/* Projects table */}
      <div className="card overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-canvas-border">
          <h2 className="text-sm font-semibold text-text-primary">Projects</h2>
          <span className="text-xs text-text-secondary">{projects.length} total</span>
        </div>

        {projects.length === 0 ? (
          <EmptyState
            icon={FolderGit2}
            title="No projects yet"
            description="Create your first project to start deploying applications."
            action={
              <Link href="/projects/new" className="btn-primary">
                <Plus size={15} /> New Project
              </Link>
            }
          />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-canvas-border bg-black/5 dark:bg-white/5">
                <th className="text-left px-6 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wide">Project</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wide">Namespace</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wide">Status</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wide">Created</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-canvas-border">
              {projects.map((p) => (
                <tr key={p.id} className="table-row-hover group">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-brand/10 flex items-center justify-center flex-shrink-0">
                        <FolderGit2 size={14} className="text-brand" />
                      </div>
                      <span className="font-medium text-text-primary">{p.name}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <code className="text-xs bg-black/5 dark:bg-white/5 text-text-secondary px-2 py-0.5 rounded font-mono">
                      {p.namespace}
                    </code>
                  </td>
                  <td className="px-6 py-4"><StatusBadge status={p.status} /></td>
                  <td className="px-6 py-4 text-xs text-text-secondary">
                    {new Date(p.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <Link
                      href={`/projects/${p.id}`}
                      className="text-xs font-medium text-brand hover:text-brand-hover opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      Open →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
