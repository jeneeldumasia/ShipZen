import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, RefreshCw, GitBranch, Package, Clock, Terminal, Activity } from "lucide-react";
import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { AutoRefresh } from "./AutoRefresh";

export const dynamic = "force-dynamic";

const STATE_STEPS = ["Queued", "Building", "Deploying", "Verifying", "Running"];

function Pipeline({ state }: { state: string }) {
  const current = STATE_STEPS.indexOf(state);
  const isFailed = state === "Failed" || state === "DLQ";

  return (
    <div className="flex items-center gap-0">
      {STATE_STEPS.map((step, i) => {
        const done    = !isFailed && current > i;
        const active  = !isFailed && current === i;
        const failed  = isFailed && i <= Math.max(current, 1);
        return (
          <div key={step} className="flex items-center">
            {/* Step node */}
            <div className="flex flex-col items-center gap-1.5">
              <div className={[
                "w-7 h-7 rounded-full border-2 flex items-center justify-center text-xs font-bold transition-all",
                done   ? "bg-emerald-500 border-emerald-500 text-white"            : "",
                active ? "bg-brand border-brand text-white shadow-glow animate-pulse-slow" : "",
                failed ? "bg-red-500 border-red-500 text-white"                    : "",
                !done && !active && !failed ? "bg-white border-slate-200 text-slate-400" : "",
              ].join(" ")}>
                {done ? "✓" : i + 1}
              </div>
              <span className={[
                "text-[10px] font-medium whitespace-nowrap",
                active ? "text-brand"    : "",
                done   ? "text-emerald-600" : "",
                failed ? "text-red-600"  : "",
                !done && !active && !failed ? "text-slate-400" : "",
              ].join(" ")}>
                {step}
              </span>
            </div>
            {/* Connector */}
            {i < STATE_STEPS.length - 1 && (
              <div className={[
                "h-0.5 w-10 mx-1 mb-5 transition-all",
                done ? "bg-emerald-400" : "bg-slate-200",
              ].join(" ")} />
            )}
          </div>
        );
      })}
    </div>
  );
}

export default async function DeploymentPage({ params }: { params: { id: string; depId: string } }) {
  let deployment;
  try { deployment = await api.deployments.get(params.id, params.depId); }
  catch { notFound(); }

  const [builds, auditLogs] = await Promise.allSettled([
    api.builds.list(params.id, params.depId),
    api.audit.list(params.id),
  ]);

  const buildList = builds.status     === "fulfilled" ? builds.value     : [];
  const auditList = auditLogs.status  === "fulfilled" ? auditLogs.value  : [];

  const isActive = ["Queued", "Building", "Deploying", "Verifying"].includes(deployment.state);
  const shortId  = deployment.deployment_id.slice(0, 8);
  const imageTag = deployment.image_uri?.split(":").pop()?.slice(0, 8) ?? "—";

  return (
    <div>
      {isActive && <AutoRefresh intervalMs={4000} />}

      <Link href={`/projects/${params.id}`} className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-6 group">
        <ArrowLeft size={14} className="group-hover:-translate-x-0.5 transition-transform" />
        Back to Project
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-xl font-semibold text-text-primary font-mono">{shortId}…</h1>
            <StatusBadge status={deployment.state} size="md" />
            {isActive && (
              <span className="flex items-center gap-1.5 text-xs text-brand font-medium">
                <RefreshCw size={11} className="animate-spin" />
                Live
              </span>
            )}
          </div>
          <p className="text-sm text-text-secondary font-mono">{deployment.repo_url}</p>
        </div>
        <a
          href={`https://grafana.deployhub.jeneeldumasia.codes/d/pod-health?orgId=1&var-namespace=tenant-${params.id}&var-deployment=${params.depId}`}
          target="_blank"
          rel="noopener noreferrer"
          className="btn-secondary text-xs py-1.5 px-3"
        >
          <Activity size={14} />
          View Metrics
        </a>
      </div>

      {/* Pipeline tracker */}
      <div className="card p-6 mb-6 overflow-x-auto">
        <Pipeline state={deployment.state} />
        {deployment.state === "Failed" && (
          <div className="mt-4 pt-4 border-t border-red-100">
            <div className="flex items-start gap-2 text-sm text-red-600">
              <Terminal size={14} className="mt-0.5 flex-shrink-0" />
              <span className="font-mono text-xs">{deployment.last_error ?? "Unknown error"}</span>
            </div>
          </div>
        )}
      </div>

      {/* Detail grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { label: "Deployment ID", value: `${shortId}…`, icon: Package, mono: true },
          { label: "Port",          value: String(deployment.port), icon: Clock },
          { label: "Image Tag",     value: `${imageTag}…`, icon: GitBranch, mono: true },
          { label: "Last Updated",  value: new Date(deployment.updated_at).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }), icon: RefreshCw },
        ].map(({ label, value, icon: Icon, mono }) => (
          <div key={label} className="card px-4 py-3">
            <div className="flex items-center gap-1.5 text-xs text-gray-400 mb-1">
              <Icon size={12} />
              {label}
            </div>
            <p className={`text-sm font-semibold text-gray-900 ${mono ? "font-mono" : ""}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Build history */}
      <div className="card overflow-hidden mb-6">
        <div className="px-6 py-4 border-b border-canvas-border">
          <h2 className="text-sm font-semibold text-gray-800">Build History</h2>
        </div>
        {buildList.length === 0 ? (
          <div className="px-6 py-8 text-sm text-gray-400 text-center">
            No builds recorded yet. Builds appear here once the builder picks up this deployment.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-canvas-border bg-slate-50/60">
                {["Build ID", "Status", "Started", "Completed", "Logs"].map(h => (
                  <th key={h} className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-canvas-border">
              {buildList.map(b => (
                <tr key={b.build_id} className="table-row-hover">
                  <td className="px-6 py-3 font-mono text-xs text-gray-600">{b.build_id.slice(0, 8)}…</td>
                  <td className="px-6 py-3"><StatusBadge status={b.status} /></td>
                  <td className="px-6 py-3 text-xs text-gray-400">{new Date(b.started_at).toLocaleString()}</td>
                  <td className="px-6 py-3 text-xs text-gray-400">{b.completed_at ? new Date(b.completed_at).toLocaleString() : "—"}</td>
                  <td className="px-6 py-3 text-xs font-mono text-gray-400 truncate max-w-xs">{b.s3_log_uri ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Audit log */}
      <div className="card overflow-hidden">
        <div className="px-6 py-4 border-b border-canvas-border">
          <h2 className="text-sm font-semibold text-gray-800">Audit Log</h2>
        </div>
        {auditList.length === 0 ? (
          <div className="px-6 py-8 text-sm text-gray-400 text-center">No audit events yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-canvas-border bg-slate-50/60">
                {["Time", "Action", "Resource", "Details"].map(h => (
                  <th key={h} className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-canvas-border">
              {auditList.map(a => (
                <tr key={a.id} className="table-row-hover">
                  <td className="px-6 py-3 text-xs text-gray-400 whitespace-nowrap">
                    {new Date(a.timestamp).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                  </td>
                  <td className="px-6 py-3">
                    <code className="text-xs bg-slate-100 text-slate-700 px-2 py-0.5 rounded font-mono font-medium">{a.action}</code>
                  </td>
                  <td className="px-6 py-3 text-xs text-gray-500">{a.resource_type}</td>
                  <td className="px-6 py-3 text-xs text-gray-400 font-mono truncate max-w-xs">{JSON.stringify(a.details)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
