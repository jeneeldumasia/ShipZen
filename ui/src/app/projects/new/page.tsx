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
    <div className="max-w-xl">
      <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-text-secondary hover:text-gray-700 mb-7 group">
        <ArrowLeft size={14} className="group-hover:-translate-x-0.5 transition-transform" />
        Back to Dashboard
      </Link>

      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl bg-brand/10 flex items-center justify-center">
          <FolderGit2 size={20} className="text-brand" />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">New Project</h1>
          <p className="text-sm text-text-secondary">A dedicated Kubernetes namespace with full isolation</p>
        </div>
      </div>

      <div className="card p-6">
        {error && (
          <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg mb-5">
            <span className="mt-0.5 text-red-500">⚠</span>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Project Name
            </label>
            <input
              className="input"
              type="text"
              value={name}
              onChange={e => handleNameChange(e.target.value)}
              placeholder="My App"
              required
              autoFocus
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Kubernetes Namespace
            </label>
            <div className="relative">
              <input
                className="input font-mono pr-24"
                type="text"
                value={namespace}
                onChange={e => setNamespace(e.target.value)}
                placeholder="my-app"
                required
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-text-secondary pointer-events-none">
                auto-generated
              </span>
            </div>
            <p className="text-xs text-text-secondary mt-1.5">
              Lowercase letters, numbers, and hyphens. 3–63 characters.
            </p>
          </div>

          {/* Preview pill */}
          {namespace && (
            <div className="flex items-center gap-2 p-3 bg-slate-50 dark:bg-white/5 rounded-lg border border-slate-200 dark:border-white/10 text-xs text-text-secondary">
              <span className="text-text-secondary">Namespace:</span>
              <code className="font-mono text-brand font-medium">{namespace}</code>
            </div>
          )}

          <div className="flex gap-3 pt-1">
            <button type="submit" disabled={loading || !name || !namespace} className="btn-primary">
              {loading && <Loader2 size={14} className="animate-spin" />}
              {loading ? "Creating…" : "Create Project"}
            </button>
            <Link href="/" className="btn-ghost">Cancel</Link>
          </div>
        </form>
      </div>
    </div>
  );
}
