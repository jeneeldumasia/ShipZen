import { cn } from "@/lib/cn";

type Status = string;

const CONFIG: Record<string, { dot: string; bg: string; text: string }> = {
  // Project
  Provisioning: { dot: "bg-yellow-400 animate-pulse",   bg: "bg-yellow-50 dark:bg-yellow-900/30  border-yellow-200 dark:border-yellow-700/50", text: "text-yellow-700 dark:text-yellow-400" },
  Ready:        { dot: "bg-emerald-400",                bg: "bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-700/50", text: "text-emerald-700 dark:text-emerald-400" },
  Terminating:  { dot: "bg-orange-400 animate-pulse",   bg: "bg-orange-50 dark:bg-orange-900/30  border-orange-200 dark:border-orange-700/50", text: "text-orange-700 dark:text-orange-400" },
  // Deployment
  Queued:       { dot: "bg-slate-400",                  bg: "bg-slate-50 dark:bg-slate-800   border-slate-200 dark:border-slate-600",  text: "text-text-secondary" },
  Building:     { dot: "bg-blue-400 animate-pulse",     bg: "bg-blue-50 dark:bg-blue-900/30    border-blue-200 dark:border-blue-700/50",   text: "text-blue-700 dark:text-blue-400" },
  Deploying:    { dot: "bg-cyan-400 animate-pulse",     bg: "bg-cyan-50 dark:bg-cyan-900/30    border-cyan-200 dark:border-cyan-700/50",   text: "text-cyan-700 dark:text-cyan-400" },
  Verifying:    { dot: "bg-violet-400 animate-pulse",   bg: "bg-violet-50 dark:bg-violet-900/30  border-violet-200 dark:border-violet-700/50", text: "text-violet-700 dark:text-violet-400" },
  Running:      { dot: "bg-emerald-400",                bg: "bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-700/50", text: "text-emerald-700 dark:text-emerald-400" },
  Failed:       { dot: "bg-red-400",                    bg: "bg-red-50 dark:bg-red-900/30     border-red-200 dark:border-red-700/50",    text: "text-red-700 dark:text-red-400" },
  Retry:        { dot: "bg-amber-400 animate-pulse",    bg: "bg-amber-50 dark:bg-amber-900/30   border-amber-200 dark:border-amber-700/50",  text: "text-amber-700 dark:text-amber-400" },
  DLQ:          { dot: "bg-red-600",                    bg: "bg-red-100 dark:bg-red-900/50    border-red-300 dark:border-red-700",    text: "text-red-800 dark:text-red-300" },
  // Build
  Success:      { dot: "bg-emerald-400",                bg: "bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-700/50", text: "text-emerald-700 dark:text-emerald-400" },
  "In Progress":{ dot: "bg-blue-400 animate-pulse",     bg: "bg-blue-50 dark:bg-blue-900/30    border-blue-200 dark:border-blue-700/50",   text: "text-blue-700 dark:text-blue-400" },
};

const FALLBACK = { dot: "bg-gray-400", bg: "bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-600", text: "text-text-secondary" };

export function StatusBadge({ status, size = "sm" }: { status: Status; size?: "sm" | "md" }) {
  const cfg = CONFIG[status] ?? FALLBACK;
  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 border rounded-full font-bold uppercase tracking-widest backdrop-blur-md",
      size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-3 py-1 text-xs",
      cfg.bg, cfg.text
    )}>
      <span className={cn("status-dot", cfg.dot)} />
      {status}
    </span>
  );
}
