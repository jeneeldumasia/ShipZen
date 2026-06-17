import { cn } from "@/lib/cn";

type Status = string;

const CONFIG: Record<string, { dot: string; bg: string; text: string }> = {
  // Project
  Provisioning: { dot: "bg-yellow-400 animate-pulse",   bg: "bg-yellow-50  border-yellow-200", text: "text-yellow-700" },
  Ready:        { dot: "bg-emerald-400",                bg: "bg-emerald-50 border-emerald-200", text: "text-emerald-700" },
  Terminating:  { dot: "bg-orange-400 animate-pulse",   bg: "bg-orange-50  border-orange-200", text: "text-orange-700" },
  // Deployment
  Queued:       { dot: "bg-slate-400",                  bg: "bg-slate-50   border-slate-200",  text: "text-text-secondary" },
  Building:     { dot: "bg-blue-400 animate-pulse",     bg: "bg-blue-50    border-blue-200",   text: "text-blue-700" },
  Deploying:    { dot: "bg-cyan-400 animate-pulse",     bg: "bg-cyan-50    border-cyan-200",   text: "text-cyan-700" },
  Verifying:    { dot: "bg-violet-400 animate-pulse",   bg: "bg-violet-50  border-violet-200", text: "text-violet-700" },
  Running:      { dot: "bg-emerald-400",                bg: "bg-emerald-50 border-emerald-200", text: "text-emerald-700" },
  Failed:       { dot: "bg-red-400",                    bg: "bg-red-50     border-red-200",    text: "text-red-700" },
  Retry:        { dot: "bg-amber-400 animate-pulse",    bg: "bg-amber-50   border-amber-200",  text: "text-amber-700" },
  DLQ:          { dot: "bg-red-600",                    bg: "bg-red-100    border-red-300",    text: "text-red-800" },
  // Build
  Success:      { dot: "bg-emerald-400",                bg: "bg-emerald-50 border-emerald-200", text: "text-emerald-700" },
  "In Progress":{ dot: "bg-blue-400 animate-pulse",     bg: "bg-blue-50    border-blue-200",   text: "text-blue-700" },
};

const FALLBACK = { dot: "bg-gray-400", bg: "bg-gray-50 border-gray-200", text: "text-text-secondary" };

export function StatusBadge({ status, size = "sm" }: { status: Status; size?: "sm" | "md" }) {
  const cfg = CONFIG[status] ?? FALLBACK;
  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 border rounded-full font-medium",
      size === "sm" ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-sm",
      cfg.bg, cfg.text
    )}>
      <span className={cn("status-dot", cfg.dot)} />
      {status}
    </span>
  );
}
