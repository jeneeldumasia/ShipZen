"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Loader2, FolderGit2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export default function NewProjectPage() {
  const router = useRouter();
  const [name, setName]           = useState("");
  const [namespace, setNamespace] = useState("");
  const [error, setError]         = useState("");
  const [loading, setLoading]     = useState(false);

  function handleNameChange(v: string) {
    setName(v);
    setNamespace(
      v.toLowerCase()
       .replace(/[^a-z0-9-]/g, "-")
       .replace(/-+/g, "-")
       .replace(/^-|-$/g, "")
       .slice(0, 63)
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const proj = await api.projects.create({ name, namespace });
      toast.success("Project created successfully");
      router.push(`/projects/${proj.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create project");
      setLoading(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto mt-8 relative animate-fade-in">
      {/* Premium Ambient Background */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none -z-10">
        <div className="absolute top-1/4 right-1/4 w-96 h-96 bg-brand/10 rounded-full blur-[128px] opacity-60 animate-pulse" style={{ animationDuration: '4s' }} />
        <div className="absolute bottom-1/4 left-1/4 w-96 h-96 bg-indigo-500/10 rounded-full blur-[128px] opacity-60 animate-pulse" style={{ animationDuration: '6s' }} />
      </div>
      <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary mb-7 group">
        <ArrowLeft size={14} className="group-hover:-translate-x-0.5 transition-transform" />
        Back to Dashboard
      </Link>

      <div className="flex flex-col items-center justify-center text-center gap-4 mb-10 mt-8">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-brand/20 to-indigo-500/10 flex items-center justify-center shadow-lg border border-brand/20 ring-4 ring-brand/5">
          <FolderGit2 size={28} className="text-brand" />
        </div>
        <div>
          <h1 className="text-3xl font-display font-bold text-text-primary tracking-tight">Create a Project</h1>
          <p className="text-sm text-text-secondary mt-2 max-w-sm mx-auto">Establish a dedicated Kubernetes namespace with complete resource isolation.</p>
        </div>
      </div>

      <div className="card p-8 md:p-10 border border-canvas-border bg-canvas-card/80 backdrop-blur-2xl shadow-2xl relative overflow-hidden group">
        {/* Subtle hover gradient inside card */}
        <div className="absolute inset-0 bg-gradient-to-br from-brand/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-700 pointer-events-none" />
        {error && (
          <div className="flex items-start gap-2.5 bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400 text-sm px-4 py-3 rounded-lg mb-5">
            <span className="mt-0.5 text-red-500">⚠</span>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="group/field relative">
            <label className="block text-sm font-medium text-text-primary mb-2 transition-colors group-focus-within/field:text-brand">
              Project Name
            </label>
            <input
              className="input transition-all duration-300 focus:shadow-[0_0_15px_rgba(var(--brand),0.15)] focus:ring-1 focus:ring-brand"
              type="text"
              value={name}
              onChange={e => handleNameChange(e.target.value)}
              placeholder="e.g. Authentication Service"
              required
              autoFocus
            />
          </div>

          <div className="group/field relative">
            <label className="block text-sm font-medium text-text-primary mb-2 transition-colors group-focus-within/field:text-brand">
              Kubernetes Namespace
            </label>
            <div className="relative">
              <input
                className="input font-mono pr-28 transition-all duration-300 focus:shadow-[0_0_15px_rgba(var(--brand),0.15)] focus:ring-1 focus:ring-brand"
                type="text"
                value={namespace}
                onChange={e => setNamespace(e.target.value)}
                placeholder="auth-service"
                required
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-mono text-text-secondary pointer-events-none uppercase tracking-widest bg-canvas-border/50 px-2 py-0.5 rounded-full">
                auto-generated
              </span>
            </div>
            <p className="text-[11px] text-text-secondary mt-2 opacity-70">
              Lowercase letters, numbers, and hyphens only. 3–63 characters.
            </p>
          </div>

          {/* Preview pill */}
          <div className={`transition-all duration-500 ease-out overflow-hidden ${namespace ? "max-h-20 opacity-100 mt-6" : "max-h-0 opacity-0 mt-0"}`}>
            <div className="flex items-center gap-3 p-4 bg-canvas-bg/50 rounded-xl border border-canvas-border shadow-inner">
              <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-xs font-medium text-text-secondary uppercase tracking-widest">Target Namespace:</span>
              <code className="font-mono text-brand font-bold text-sm bg-brand/10 px-2 py-0.5 rounded-md">{namespace}</code>
            </div>
          </div>

          <div className="flex items-center gap-4 pt-6 mt-4 border-t border-canvas-border">
            <button type="submit" disabled={loading || !name || !namespace} className="btn-primary flex-1 py-3 text-sm font-bold tracking-wide shadow-lg hover:shadow-brand/20 transition-all hover:-translate-y-0.5 disabled:transform-none">
              {loading ? <Loader2 size={16} className="animate-spin" /> : null}
              {loading ? "PROVISIONING..." : "CREATE PROJECT"}
            </button>
            <Link href="/" className="btn-ghost py-3 px-6 text-sm font-medium hover:bg-canvas-border/50">Cancel</Link>
          </div>
        </form>
      </div>
    </div>
  );
}
