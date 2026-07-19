import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Plus, Rocket, GitBranch, CheckCircle2, AlertTriangle, Clock, Zap } from "lucide-react";
import { api, Deployment } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { MetricCard } from "@/components/MetricCard";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { DeleteProjectButton } from "./DeleteProjectButton";
import { EnvVars } from "./EnvVars";
import { Webhooks } from "./Webhooks";
import { ProjectShortcuts } from "./ProjectShortcuts";

export const dynamic = "force-dynamic";

export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = await params;
  let project;
  let deployments: Deployment[] = [];

  try { project = await api.projects.get(resolvedParams.id); }
  catch { notFound(); }

  try { deployments = await api.deployments.list(resolvedParams.id); }
  catch {}

  const running  = deployments.filter(d => d.state === "Running").length;
  const failed   = deployments.filter(d => d.state === "Failed").length;
  const building = deployments.filter(d => ["Queued","Building","Deploying","Verifying"].includes(d.state)).length;

  return (
    <div>
      <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary mb-6 group">
        <ArrowLeft size={14} className="group-hover:-translate-x-0.5 transition-transform" />
        All Projects
      </Link>

      <PageHeader
        title={project.name}
        description={
          <span className="flex items-center gap-2 mt-1">
            <code className="text-xs bg-black/5 dark:bg-white/5 text-text-secondary px-2 py-0.5 rounded font-mono">{project.namespace}</code>
            <span className="text-canvas-border">·</span>
            <span className="text-xs text-text-secondary">
              Created {new Date(project.created_at).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
            </span>
          </span>
        }
        actions={
          <>
            <Link href={`/projects/${project.id}/deployments/new`} className="btn-primary">
              <Plus size={15} /> Deploy
            </Link>
            <DeleteProjectButton projectId={project.id} projectName={project.name} />
          </>
        }
      />

      {/* Status badge inline */}
      <div className="mb-6 -mt-4">
        <StatusBadge status={project.status} size="md" />
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <MetricCard label="Total"      value={deployments.length} icon={Zap} />
        <MetricCard label="Running"    value={running}  icon={CheckCircle2} color="green" />
        <MetricCard label="Building"   value={building} icon={Clock}        color="blue" />
        <MetricCard label="Failed"     value={failed}   icon={AlertTriangle} color="red" />
      </div>

      {/* Deployments */}
      <div className="card overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-canvas-border">
          <h2 className="text-sm font-semibold text-text-primary">Deployments</h2>
          <Link href={`/projects/${project.id}/deployments/new`} className="btn-primary text-xs py-1.5 px-3">
            <Plus size={13} /> Deploy
          </Link>
        </div>

        {deployments.length === 0 ? (
          <EmptyState
            icon={Rocket}
            title="No deployments yet"
            description="Submit a repository URL to deploy it to this project's namespace."
            action={
              <Link href={`/projects/${project.id}/deployments/new`} className="btn-primary">
                <Rocket size={15} /> Deploy Now
              </Link>
            }
          />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-canvas-border bg-black/5 dark:bg-white/5">
                <th className="text-left px-6 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wide">Repository</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wide">State</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wide">Port</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wide">Updated</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-canvas-border">
              {deployments.map((d) => (
                <tr key={d.deployment_id} className="table-row-hover group">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2.5">
                      <GitBranch size={14} className="text-text-secondary flex-shrink-0" />
                      <span className="font-mono text-xs text-text-primary truncate max-w-xs">{d.repo_url}</span>
                    </div>
                    {d.last_error && d.state === "Failed" && (
                      <p className="text-xs text-red-500 mt-1 ml-[22px] truncate max-w-xs">{d.last_error}</p>
                    )}
                  </td>
                  <td className="px-6 py-4"><StatusBadge status={d.state} /></td>
                  <td className="px-6 py-4">
                    <code className="text-xs bg-black/5 dark:bg-white/5 text-text-secondary px-1.5 py-0.5 rounded">{d.port}</code>
                  </td>
                  <td className="px-6 py-4 text-xs text-text-secondary">
                    {new Date(d.updated_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <Link
                      href={`/projects/${project.id}/deployments/${d.deployment_id}`}
                      className="text-xs font-medium text-brand hover:text-brand-hover opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      View →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <EnvVars projectId={project.id} />
      <Webhooks />
      <ProjectShortcuts projectId={project.id} />
    </div>
  );
}
