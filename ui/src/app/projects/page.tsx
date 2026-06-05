import Link from "next/link";
import { Plus, FolderGit2, Clock } from "lucide-react";
import { api, Project } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

export const dynamic = "force-dynamic";
export const metadata = { title: "Projects" };

async function getProjects(): Promise<Project[]> {
  try { return await api.projects.list(); }
  catch { return []; }
}

export default async function ProjectsPage() {
  const projects = await getProjects();

  return (
    <div>
      <PageHeader
        title="Projects"
        description="Manage your applications and deployments"
        actions={
          <Link href="/projects/new" className="btn-primary">
            <Plus size={15} />
            New Project
          </Link>
        }
      />

      {projects.length === 0 ? (
        <div className="card overflow-hidden mt-6">
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
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {projects.map((p) => (
            <Link key={p.id} href={`/projects/${p.id}`} className="block group">
              <div className="card p-5 h-full hover:border-brand/40 transition-colors">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-brand/10 flex items-center justify-center flex-shrink-0 group-hover:bg-brand/15 transition-colors">
                      <FolderGit2 size={20} className="text-brand" />
                    </div>
                    <div>
                      <h3 className="font-semibold text-gray-900 group-hover:text-brand transition-colors">{p.name}</h3>
                      <p className="text-xs text-gray-500 mt-0.5">{p.namespace}</p>
                    </div>
                  </div>
                  <StatusBadge status={p.status} />
                </div>
                
                <div className="mt-6 pt-4 border-t border-slate-100 flex items-center justify-between text-xs text-gray-500">
                  <div className="flex items-center gap-1.5">
                    <Clock size={13} className="text-gray-400" />
                    <span>Created {new Date(p.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
