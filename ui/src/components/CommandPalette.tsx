"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import { FolderGit2, Plus, Rocket, RefreshCw, Terminal, X } from "lucide-react";
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
        <div className="bg-zinc-950 w-full max-w-xl rounded-xl border border-zinc-800 shadow-2xl overflow-hidden flex flex-col">
          <div className="flex items-center px-4 border-b border-zinc-800">
            <Command.Input 
              placeholder="Search projects or run a command..." 
              className="w-full bg-transparent text-sm text-zinc-100 placeholder:text-text-secondary py-4 focus:outline-none"
            />
            <button onClick={() => setOpen(false)} className="text-text-secondary hover:text-zinc-300 ml-2">
              <X size={16} />
            </button>
          </div>
          
          <Command.List className="max-h-[300px] overflow-y-auto p-2">
            <Command.Empty className="py-6 text-center text-sm text-text-secondary">
              {loading ? "Loading..." : "No results found."}
            </Command.Empty>

            <Command.Group heading="Actions" className="px-2 py-1.5 text-xs font-medium text-text-secondary">
              <Command.Item 
                onSelect={() => { setOpen(false); router.push("/projects/new"); }}
                className="flex items-center gap-2 px-3 py-2 text-sm text-zinc-300 rounded-md cursor-pointer aria-selected:bg-brand aria-selected:text-white transition-colors"
              >
                <Plus size={14} /> New Project
                <span className="ml-auto text-[10px] text-text-secondary aria-selected:text-white/70">N</span>
              </Command.Item>
              <Command.Item 
                onSelect={() => { setOpen(false); router.push("/"); }}
                className="flex items-center gap-2 px-3 py-2 text-sm text-zinc-300 rounded-md cursor-pointer aria-selected:bg-brand aria-selected:text-white transition-colors"
              >
                <Terminal size={14} /> Dashboard
              </Command.Item>
            </Command.Group>

            {projects.length > 0 && (
              <Command.Group heading="Projects" className="px-2 py-1.5 text-xs font-medium text-text-secondary mt-2">
                {projects.map((p) => (
                  <Command.Item
                    key={p.id}
                    value={p.name}
                    onSelect={() => { setOpen(false); router.push(`/projects/${p.id}`); }}
                    className="flex items-center gap-2 px-3 py-2 text-sm text-zinc-300 rounded-md cursor-pointer aria-selected:bg-zinc-800 aria-selected:text-white transition-colors"
                  >
                    <FolderGit2 size={14} className="text-text-secondary" />
                    {p.name}
                    <span className="ml-2 text-[10px] text-text-secondary font-mono">{p.namespace}</span>
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
