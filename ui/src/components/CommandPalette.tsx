"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import { FolderGit2, Plus, Terminal, X } from "lucide-react";
import { api, Project } from "@/lib/api";

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      // Cmd+K or Ctrl+K
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((open) => !open);
      }
      
      // Global shortcut N: New Project
      if (e.key.toLowerCase() === "n" && !e.metaKey && !e.ctrlKey && e.target === document.body) {
        e.preventDefault();
        router.push("/projects/new");
      }
    };

    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, [router]);

  useEffect(() => {
    if (open && projects.length === 0) {
      setLoading(true);
      api.projects.list()
        .then(res => setProjects(res))
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  }, [open, projects.length]);

  return (
    <>
      <Command.Dialog
        open={open}
        onOpenChange={setOpen}
        label="Global Command Menu"
        className="fixed inset-0 z-50 flex items-start justify-center pt-32 bg-black/50 backdrop-blur-sm animate-in fade-in duration-200"
      >
        <div className="bg-canvas-bg w-full max-w-2xl rounded-none border-2 border-text-primary shadow-[24px_24px_0_0_rgba(0,0,0,1)] dark:shadow-[24px_24px_0_0_rgba(255,255,255,1)] overflow-hidden flex flex-col transition-all duration-300">
          <div className="flex items-center px-6 border-b-2 border-text-primary">
            <Command.Input 
              placeholder="Search projects or run a command..." 
              className="w-full bg-transparent text-xl font-display font-bold text-text-primary placeholder:text-text-secondary py-6 focus:outline-none"
            />
            <button onClick={() => setOpen(false)} className="text-text-secondary hover:text-text-primary ml-2 transition-colors">
              <X size={24} />
            </button>
          </div>
          
          <Command.List className="max-h-[400px] overflow-y-auto p-0">
            <Command.Empty className="py-12 text-center text-sm font-mono uppercase tracking-widest text-text-secondary">
              {loading ? "Loading..." : "No results found."}
            </Command.Empty>

            <Command.Group heading="Actions" className="px-4 py-3 text-[10px] font-mono uppercase tracking-widest text-text-secondary">
              <Command.Item 
                onSelect={() => { setOpen(false); router.push("/projects/new"); }}
                className="flex items-center gap-3 px-4 py-4 text-base font-bold text-text-primary cursor-pointer aria-selected:bg-text-primary aria-selected:text-canvas-bg transition-colors group"
              >
                <Plus size={18} /> New Project
                <span className="ml-auto text-[10px] font-mono border border-current px-1 group-aria-selected:border-canvas-bg">N</span>
              </Command.Item>
              <Command.Item 
                onSelect={() => { setOpen(false); router.push("/"); }}
                className="flex items-center gap-3 px-4 py-4 text-base font-bold text-text-primary cursor-pointer aria-selected:bg-text-primary aria-selected:text-canvas-bg transition-colors"
              >
                <Terminal size={18} /> Dashboard
              </Command.Item>
              <Command.Item 
                onSelect={() => { setOpen(false); router.push("/admin"); }}
                className="flex items-center gap-3 px-4 py-4 text-base font-bold text-text-primary cursor-pointer aria-selected:bg-text-primary aria-selected:text-canvas-bg transition-colors"
              >
                <Terminal size={18} /> Admin Console
              </Command.Item>
            </Command.Group>

            {projects.length > 0 && (
              <Command.Group heading="Projects" className="px-4 py-3 text-[10px] font-mono uppercase tracking-widest text-text-secondary border-t border-canvas-border">
                {projects.map((p) => (
                  <Command.Item
                    key={p.id}
                    value={p.name}
                    onSelect={() => { setOpen(false); router.push(`/projects/${p.id}`); }}
                    className="flex items-center gap-3 px-4 py-4 text-base font-bold text-text-primary cursor-pointer aria-selected:bg-text-primary aria-selected:text-canvas-bg transition-colors"
                  >
                    <FolderGit2 size={18} className="text-current opacity-50" />
                    {p.name}
                    <span className="ml-2 text-[10px] font-mono uppercase tracking-widest opacity-50">{p.namespace}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
        </div>
      </Command.Dialog>
      
      {/* Global styling for cmdk provided by tailwind, but we need to hide the dialog wrapper visually if not needed, cmdk handles it */}
    </>
  );
}
