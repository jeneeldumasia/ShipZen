"use client";

import { useState, useEffect } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Loader2, ChevronDown, ChevronUp, Globe, GitBranch, Rocket, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export default function NewDeploymentPage() {
  const router = useRouter();
  const { id: projectId } = useParams<{ id: string }>();

  const [repoUrl, setRepoUrl]           = useState("");
  const [branch, setBranch]             = useState("main");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [port, setPort]                 = useState(8080);
  const [error, setError]               = useState("");
  const [loading, setLoading]           = useState(false);

  // New states for branch fetching
  const [branches, setBranches]               = useState<string[]>([]);
  const [loadingBranches, setLoadingBranches] = useState(false);
  const [branchError, setBranchError]         = useState<string | null>(null);
  const [totalBranches, setTotalBranches]     = useState(0);

  // Debounced branch fetch
  useEffect(() => {
    // Reset states on change
    setBranches([]);
    setBranchError(null);
    setLoadingBranches(false);
    setTotalBranches(0);

    if (!repoUrl.includes("github.com")) {
      return;
    }

    setLoadingBranches(true);
    const timer = setTimeout(async () => {
      try {
        const data = await api.github.branches(repoUrl);
        setBranches(data.branches);
        setTotalBranches(data.total);
        if (data.branches.includes("main")) {
          setBranch("main");
        } else if (data.branches.length > 0) {
          setBranch(data.branches[0]);
        }
      } catch (err: unknown) {
        setBranchError(err instanceof Error ? err.message : "Failed to load branches");
      } finally {
        setLoadingBranches(false);
      }
    }, 600);

    return () => clearTimeout(timer);
  }, [repoUrl]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const dep = await api.deployments.create(projectId, { repo_url: repoUrl, branch, port });
      toast.success("Deployment submitted successfully");
      router.push(`/projects/${projectId}/deployments/${dep.deployment_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to submit deployment");
      setLoading(false);
    }
  }

  // Derive repo name for display
  const repoName = repoUrl ? repoUrl.split("/").slice(-2).join("/").replace(".git", "") : null;

  return (
    <div className="max-w-xl">
      <Link href={`/projects/${projectId}`} className="inline-flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary mb-7 group">
        <ArrowLeft size={14} className="group-hover:-translate-x-0.5 transition-transform" />
        Back to Project
      </Link>

      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl bg-brand/10 flex items-center justify-center">
          <Rocket size={20} className="text-brand" />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">New Deployment</h1>
          <p className="text-sm text-text-secondary">Paste your repo — the platform handles the rest</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="card p-6 space-y-5">
        {error && (
          <div className="flex items-start gap-2.5 bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400 text-sm px-4 py-3 rounded-lg">
            <span className="mt-0.5">⚠</span>
            {error}
          </div>
        )}

        {/* Repo URL */}
        <div>
          <label className="block text-sm font-medium text-text-primary mb-1.5">Repository URL</label>
          <div className="relative">
            <Globe size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
            <input
              className="input pl-9 font-mono"
              type="text"
              value={repoUrl}
              onChange={e => setRepoUrl(e.target.value)}
              placeholder="https://github.com/your-org/your-repo"
              required
              autoFocus
            />
          </div>
          <p className="text-xs text-text-secondary mt-1.5">
            Public or private GitHub/GitLab repo. No Dockerfile needed — language is auto-detected.
          </p>
        </div>

        {/* Branch */}
        <div>
          <label className="block text-sm font-medium text-text-primary mb-1.5">Branch</label>
          <div className="relative">
            {loadingBranches ? (
              <Loader2 size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary animate-spin" />
            ) : (
              <GitBranch size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none" />
            )}
            
            {branches.length > 0 && !branchError ? (
              <select
                className="input pl-9 font-mono appearance-none"
                value={branch}
                onChange={e => setBranch(e.target.value)}
                disabled={loadingBranches}
              >
                {branches.map(b => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
            ) : (
              <input
                className="input pl-9 font-mono"
                type="text"
                value={branch}
                onChange={e => setBranch(e.target.value)}
                placeholder="main"
                disabled={loadingBranches}
              />
            )}
          </div>
          {repoUrl && !loadingBranches && branches.length === 0 && (
            <p className="text-xs text-text-secondary mt-1.5">Enter branch name manually</p>
          )}
          {totalBranches >= 300 && (
            <p className="text-xs text-text-secondary mt-1.5">Showing first 300 branches</p>
          )}
        </div>

        {/* Advanced */}
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary font-medium"
          >
            <Settings2 size={13} />
            Advanced options
            {showAdvanced ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>

          {showAdvanced && (
            <div className="mt-4 pt-4 border-t border-canvas-border space-y-4 animate-fade-in">
              <div>
                <label className="block text-sm font-medium text-text-primary mb-1.5">Container Port</label>
                <input
                  type="number"
                  min={1}
                  max={65535}
                  value={port}
                  onChange={e => setPort(Number(e.target.value))}
                  className="input w-32"
                />
                <p className="text-xs text-text-secondary mt-1.5">
                  The port your app listens on. Defaults to 8080.
                  Can also be set via <code className="bg-canvas-border px-1 rounded">shipzen.yaml</code> in your repo.
                </p>
              </div>
            </div>
          )}
        </div>

        {/* "What happens next" preview */}
        {repoName && (
          <div className="rounded-lg border border-brand/20 bg-brand/5 p-4 animate-fade-in">
            <p className="text-xs font-semibold text-brand mb-2.5">Deployment pipeline</p>
            <ol className="space-y-2">
              {[
                `Clone ${repoName} @ ${branch}`,
                "Detect runtime and build with Cloud Native Buildpacks",
                "Push image to platform registry",
                "Create Kubernetes deployment in your namespace",
                "Route traffic via platform gateway",
              ].map((step, i) => (
                <li key={i} className="flex items-center gap-2.5 text-xs text-brand/80">
                  <span className="w-4 h-4 rounded-full bg-brand/15 text-brand flex items-center justify-center font-semibold flex-shrink-0 text-[10px]">
                    {i + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ol>
          </div>
        )}

        <div className="flex gap-3 pt-1">
          <button type="submit" disabled={loading || !repoUrl} className="btn-primary">
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Rocket size={14} />}
            {loading ? "Submitting…" : "Deploy"}
          </button>
          <Link href={`/projects/${projectId}`} className="btn-ghost">Cancel</Link>
        </div>
      </form>
    </div>
  );
}
