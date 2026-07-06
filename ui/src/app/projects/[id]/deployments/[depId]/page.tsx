import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, RefreshCw, GitBranch, Package, Clock, Terminal, Activity } from "lucide-react";
import { api, Build } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { AutoRefresh } from "./AutoRefresh";
import { RedeployButton } from "./RedeployButton";
import { LogViewer } from "./LogViewer";
import { LiveLogPanel } from "./LiveLogPanel";
import { auth } from "@/auth";

export const dynamic = "force-dynamic";

const STATE_STEPS = ["Queued", "Building", "Deploying", "Verifying", "Running"];

function Pipeline({ state, builds }: { state: string, builds: Build[] }) {
  const isFailed = state === "Failed" || state === "DLQ";
  
  let failIndex = -1;
  if (isFailed) {
    if (builds.length === 0) failIndex = 0; // Failed in Queued
    else if (builds.some(b => b.status === "Failed")) failIndex = 1; // Failed in Building
    else failIndex = 2; // Failed in Deploying or later
  }

  const current = isFailed ? failIndex : STATE_STEPS.indexOf(state);

  return (
    <div className="flex items-center gap-0">
      {STATE_STEPS.map((step, i) => {
        const done    = (!isFailed && current > i) || (isFailed && i < current);
        const active  = !isFailed && current === i;
        const failed  = isFailed && current === i;
        return (
          <div key={step} className="flex items-center">
            {/* Step node */}
            <div className="flex flex-col items-center gap-1.5">
              <div className={[
                "w-7 h-7 rounded-full border-2 flex items-center justify-center text-xs font-bold transition-all",
                done   ? "bg-emerald-500 border-emerald-500 text-canvas-bg"            : "",
                active ? "bg-brand border-brand text-canvas-bg shadow-glow animate-pulse-slow" : "",
                failed ? "bg-red-500 border-red-500 text-canvas-bg"    : "",
                !done && !active && !failed ? "bg-white border-slate-200 text-text-secondary" : "",
              ].join(" ")}>
                {done ? "✓" : failed ? "✗" : i + 1}
              </div>
              <span className={[
                "text-[10px] font-medium whitespace-nowrap",
                active ? "text-brand"    : "",
                done   ? "text-emerald-600" : "",
                failed ? "text-red-600"  : "",
                !done && !active && !failed ? "text-text-secondary" : "",
              ].join(" ")}>
                {failed ? "Failed" : step}
              </span>
            </div>
            {/* Connector */}
            {i < STATE_STEPS.length - 1 && (
              <div className={[
                "h-0.5 w-10 mx-1 mb-5 transition-all",
                done ? "bg-emerald-400" : failed && i === current ? "bg-red-200" : "bg-slate-200",
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
  let project;
  try { 
    deployment = await api.deployments.get(params.id, params.depId); 
    project = await api.projects.get(params.id);
  }
  catch { notFound(); }

  const session = await auth();
  const token = (session as { accessToken?: string })?.accessToken;

  const [builds, auditLogs] = await Promise.allSettled([
    api.builds.list(params.id, params.depId),
    api.audit.list(params.id),
  ]);

  const buildList = builds.status     === "fulfilled" ? builds.value     : [];
  const auditList = auditLogs.status  === "fulfilled" ? auditLogs.value  : [];

  const isActive = ["Queued", "Building", "Deploying", "Verifying"].includes(deployment.state);
  // Also watch states that just transitioned to terminal — the WS handles cleanup internally
  const needsLiveUpdates = isActive;
  const shortId  = deployment.deployment_id.slice(0, 8);
  const imageTag = deployment.image_uri?.split(":").pop()?.slice(0, 8) ?? "—";

  return (
    <div>
      {needsLiveUpdates && <AutoRefresh projectId={params.id} deploymentId={params.depId} token={token} />}

      <Link href={`/projects/${params.id}`} className="inline-flex items-center gap-1.5 text-sm text-text-secondary hover:text-gray-700 mb-6 group">
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
                In Progress
              </span>
            )}
            {deployment.state === "Running" && (
              <a 
                href={`http://${shortId}-${project.name}-${process.env.NEXT_PUBLIC_APP_DOMAIN}`} 
                target="_blank" 
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 text-xs bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 px-2 py-0.5 rounded font-medium hover:bg-emerald-500/20 transition-colors"
              >
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                Live: {shortId}-{project.name}-{process.env.NEXT_PUBLIC_APP_DOMAIN}
              </a>
            )}
          </div>
          <p className="text-sm text-text-secondary font-mono">{deployment.repo_url}</p>
        </div>
          <div className="flex items-center gap-2">
            <a
              href={`https://grafana-shipzen.jeneeldumasia.codes/d/pod-health?orgId=1&var-namespace=${project.namespace}&var-deployment=${params.depId}`}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary text-xs py-1.5 px-3"
            >
              <Activity size={14} />
              View Metrics
            </a>
            <RedeployButton projectId={params.id} repoUrl={deployment.repo_url} port={deployment.port} />
          </div>
        </div>

      {/* Pipeline tracker */}
      <div className="card p-6 mb-6 overflow-x-auto">
        <Pipeline state={deployment.state} builds={buildList} />
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
            <div className="flex items-center gap-1.5 text-xs text-text-secondary mb-1">
              <Icon size={12} />
              {label}
            </div>
            <p className={`text-sm font-semibold text-text-primary ${mono ? "font-mono" : ""}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Live log panel — shown inline while build is active */}
      {isActive && (
        <div className="mb-6">
          <LiveLogPanel
            projectId={params.id}
            deploymentId={params.depId}
            token={token}
          />
        </div>
      )}

      {/* Build history */}
      <div className="card overflow-hidden mb-6">
        <div className="px-6 py-4 border-b border-canvas-border">
          <h2 className="text-sm font-semibold text-text-primary">Build History</h2>
        </div>
        {buildList.length === 0 ? (
          <div className="px-6 py-8 text-sm text-text-secondary text-center">
            No builds recorded yet. Builds appear here once the builder picks up this deployment.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-canvas-border bg-slate-50/60">
                {["Build ID", "Status", "Started", "Completed", "Logs"].map(h => (
                  <th key={h} className="text-left px-6 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-canvas-border">
              {buildList.map(b => (
                <tr key={b.build_id} className="table-row-hover">
                  <td className="px-6 py-3 font-mono text-xs text-text-secondary">{b.build_id.slice(0, 8)}…</td>
                  <td className="px-6 py-3"><StatusBadge status={b.status} /></td>
                  <td className="px-6 py-3 text-xs text-text-secondary">{new Date(b.started_at).toLocaleString()}</td>
                  <td className="px-6 py-3 text-xs text-text-secondary">{b.completed_at ? new Date(b.completed_at).toLocaleString() : "—"}</td>
                  <td className="px-6 py-3">
                    {b.s3_log_uri ? (
                      <LogViewer
                        projectId={params.id}
                        deploymentId={params.depId}
                        buildId={b.build_id}
                        deploymentState={deployment.state}
                        token={token}
                      />
                    ) : (
                      <span className="text-xs text-text-secondary">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Audit log */}
      <div className="card overflow-hidden">
        <div className="px-6 py-4 border-b border-canvas-border">
          <h2 className="text-sm font-semibold text-text-primary">Audit Log</h2>
        </div>
        {auditList.length === 0 ? (
          <div className="px-6 py-8 text-sm text-text-secondary text-center">No audit events yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-canvas-border bg-slate-50/60">
                {["Time", "Action", "Resource", "Details"].map(h => (
                  <th key={h} className="text-left px-6 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-canvas-border">
              {auditList.map(a => (
                <tr key={a.id} className="table-row-hover">
                  <td className="px-6 py-3 text-xs text-text-secondary whitespace-nowrap">
                    {new Date(a.timestamp).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                  </td>
                  <td className="px-6 py-3">
                    <code className="text-xs bg-slate-100 text-slate-700 px-2 py-0.5 rounded font-mono font-medium">{a.action}</code>
                  </td>
                  <td className="px-6 py-3 text-xs text-text-secondary">{a.resource_type}</td>
                  <td className="px-6 py-3 text-xs text-text-secondary font-mono truncate max-w-xs">{JSON.stringify(a.details)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
