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
  
  // Intelligent greeting based on time
  const hour = new Date().getHours();
  let greeting = "Good evening";
  if (hour < 12) greeting = "Good morning";
  else if (hour < 18) greeting = "Good afternoon";

  const allReady = projects.every(p => p.status === "Ready");
  const notReadyCount = projects.filter(p => p.status !== "Ready").length;
  const systemStatus = allReady ? "All systems operational." : `${notReadyCount} project${notReadyCount > 1 ? 's' : ''} need${notReadyCount === 1 ? 's' : ''} attention.`;

  return (
    <div className="w-full flex flex-col items-center justify-center min-h-[70vh] animate-fade-in">
      {/* Intelligent Greeting */}
      <div className="text-center mb-24">
        <h1 className="text-5xl font-display font-bold text-text-primary tracking-tighter mb-4">{greeting}.</h1>
        <p className="text-lg text-text-secondary font-serif italic tracking-wide">{systemStatus}</p>
      </div>

      {/* The Canvas (Projects as Minimalist Blocks) */}
      <div className="w-full max-w-4xl">
        {projects.length === 0 ? (
          <div className="flex flex-col items-center justify-center text-center opacity-80 mt-12">
            <p className="text-2xl font-display text-text-primary tracking-tight mb-4">No Projects Found</p>
            <p className="text-sm text-text-secondary mb-8 max-w-sm">Deploy your first application to get started.</p>
            <Link href="/projects/new" className="btn-primary">
              <Plus size={16} />
              Create Project
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {projects.map((p) => (
              <Link 
                href={`/projects/${p.id}`} 
                key={p.id}
                className="group relative flex flex-col items-center justify-center py-16 px-8 border border-transparent hover:border-canvas-border transition-all duration-[500ms] ease-[cubic-bezier(0.23,1,0.32,1)] hover:-translate-y-2"
              >
                {/* Aura Glow on Hover */}
                <div className="absolute inset-0 opacity-0 group-hover:opacity-100 bg-brand/5 blur-2xl transition-opacity duration-700 -z-10 rounded-full" />
                
                <h2 className="text-3xl font-display font-bold text-text-primary tracking-tight mb-3 group-hover:text-brand transition-colors">{p.name}</h2>
                <div className="flex items-center gap-3">
                  <StatusBadge status={p.status} size="sm" />
                  <span className="text-[10px] font-mono text-text-secondary uppercase tracking-widest">{p.namespace}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
