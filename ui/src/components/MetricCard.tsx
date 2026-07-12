import { cn } from "@/lib/cn";
import type { LucideIcon } from "lucide-react";

export function MetricCard({
  label,
  value,
  icon: Icon,
  color = "default",
  trend,
}: {
  label: string;
  value: number | string;
  icon?: LucideIcon;
  color?: "default" | "green" | "blue" | "red" | "amber";
  trend?: string;
}) {
  const colors = {
    default: { icon: "text-slate-500 bg-slate-100 dark:bg-slate-800",  value: "text-text-primary" },
    green:   { icon: "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30", value: "text-emerald-700 dark:text-emerald-400" },
    blue:    { icon: "text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/30",   value: "text-blue-700 dark:text-blue-400" },
    red:     { icon: "text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/30",     value: "text-red-700 dark:text-red-400" },
    amber:   { icon: "text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30", value: "text-amber-700 dark:text-amber-400" },
  };

  const c = colors[color];

  return (
    <div className="metric-tile group hover:shadow-card-hover transition-shadow duration-200">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-text-secondary uppercase tracking-wide">{label}</p>
        {Icon && (
          <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center", c.icon)}>
            <Icon size={15} />
          </div>
        )}
      </div>
      <p className={cn("text-4xl font-display font-bold tabular-nums mt-1", c.value)}>{value}</p>
      {trend && <p className="text-xs text-text-secondary mt-0.5">{trend}</p>}
    </div>
  );
}
