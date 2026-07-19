import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, RefreshCw, Activity, Terminal } from "lucide-react";
import { api, Build } from "@/lib/api";
import { AutoRefresh } from "./AutoRefresh";
import { RedeployButton } from "./RedeployButton";
import { RestartAppButton } from "./RestartAppButton";
import { LiveLogPanel } from "./LiveLogPanel";
import { auth } from "@/auth";

export const dynamic = "force-dynamic";

function Pulse({ state, url }: { state: string, url?: string }) {
  const isFailed = state === "Failed" || state === "DLQ";
  const isLive = state === "Ready" || state === "Running" || state === "Success";
  const isActive = ["Queued", "Building", "Deploying", "Verifying"].includes(state);

  return (
    <div className="flex flex-col items-center justify-center py-32 relative w-full max-w-2xl mx-auto">
      {/* The Aura */}
      <div className={`absolute inset-0 blur-3xl opacity-20 -z-10 rounded-full transition-all duration-1000 ${
        isFailed ? "bg-red-500" : isLive ? "bg-emerald-500" : isActive ? "bg-brand animate-pulse" : "bg-transparent"
      }`} />
      
      {/* The Core Ring */}
      <div className={`relative w-64 h-64 rounded-full flex flex-col items-center justify-center border-2 transition-all duration-[2000ms] ease-out ${
        isFailed ? "border-red-500 scale-95" : isLive ? "border-emerald-500 scale-105" : isActive ? "border-brand scale-100" : "border-canvas-border"
      }`}>
        
        {/* Animated Inner Pulse for active states */}
        {isActive && (
          <div className="absolute inset-0 rounded-full border border-brand animate-ping opacity-20" style={{ animationDuration: '3s' }} />
        )}
        
        <h2 className={`text-4xl font-display font-bold uppercase tracking-widest ${
          isFailed ? "text-red-500" : isLive ? "text-emerald-500" : isActive ? "text-text-primary" : "text-text-secondary"
        }`}>
          {state}
        </h2>
      </div>

      {isLive && url && (
        <a 
          href={url} 
          target="_blank" 
          rel="noopener noreferrer"
          className="mt-16 text-3xl font-display font-bold text-text-primary hover:text-brand transition-colors border-b-2 border-transparent hover:border-brand pb-1"
        >
          {url.replace("http://", "")}
        </a>
      )}
    </div>
  );
}

export default async function DeploymentPage(props: { params: Promise<{ id: string; depId: string }> }) {
  const params = await props.params;
  let deployment;
  let project;
  try { 
    deployment = await api.deployments.get(params.id, params.depId); 
    project = await api.projects.get(params.id);
  }
  catch { notFound(); }

  const session = await auth();
  const token = (session as { accessToken?: string })?.accessToken;
  const isActive = ["Queued", "Building", "Deploying", "Verifying"].includes(deployment.state);
  const needsLiveUpdates = isActive;
  const shortId = deployment.deployment_id.slice(0, 8);
  const appDomain = process.env.NEXT_PUBLIC_APP_DOMAIN;
  const appUrl = appDomain ? `http://${shortId}-${project.name}.${appDomain}` : `http://localhost:${deployment.port}`;

  return (
    <div className="w-full animate-fade-in relative">
      {needsLiveUpdates && <AutoRefresh projectId={params.id} deploymentId={params.depId} token={token} />}

      {/* Header */}
      <div className="flex items-center justify-between mb-16">
        <Link href={`/projects/${params.id}`} className="inline-flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-text-secondary hover:text-text-primary transition-colors group">
          <ArrowLeft size={16} className="group-hover:-translate-x-1 transition-transform" />
          {project.name}
        </Link>

        <div className="flex items-center gap-4">
          <a
            href={`https://grafana-shipzen.jeneeldumasia.codes/d/pod-health?orgId=1&var-namespace=${project.namespace}&var-deployment=${params.depId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-ghost"
          >
            <Activity size={16} /> Metrics
          </a>
          <RestartAppButton projectId={params.id} deploymentId={params.depId} />
          <RedeployButton projectId={params.id} repoUrl={deployment.repo_url} port={deployment.port} />
        </div>
      </div>

      <div className="text-center mb-8">
        <p className="text-lg font-mono text-text-secondary opacity-50">{deployment.repo_url}</p>
        <p className="text-xs font-mono text-text-secondary uppercase tracking-widest mt-2">{shortId} • PORT {deployment.port}</p>
      </div>

      {/* The Pulse */}
      <Pulse state={deployment.state} url={appUrl} />

      {/* Error state */}
      {deployment.state === "Failed" && deployment.last_error && (
        <div className="max-w-2xl mx-auto mt-8 p-6 border border-red-500/20 bg-red-500/10 text-red-600 dark:text-red-400 font-mono text-sm">
          <div className="flex items-center gap-2 mb-2 font-bold uppercase tracking-widest text-xs">
            <Terminal size={14} /> Critical Failure
          </div>
          {deployment.last_error}
        </div>
      )}

      {/* Live Cinematic Logs */}
      {isActive && (
        <div className="max-w-4xl mx-auto mt-16 opacity-100 transition-opacity duration-500">
          <LiveLogPanel
            projectId={params.id}
            deploymentId={params.depId}
            token={token}
          />
        </div>
      )}
    </div>
  );
}
