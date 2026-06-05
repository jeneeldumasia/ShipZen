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
    default: { icon: "text-gray-400 bg-gray-100",  value: "text-gray-900" },
    green:   { icon: "text-emerald-600 bg-emerald-50", value: "text-emerald-700" },
    blue:    { icon: "text-blue-600 bg-blue-50",   value: "text-blue-700" },
    red:     { icon: "text-red-600 bg-red-50",     value: "text-red-700" },
    amber:   { icon: "text-amber-600 bg-amber-50", value: "text-amber-700" },
  };

  const c = colors[color];

  return (
    <div className="metric-tile group hover:shadow-card-hover transition-shadow duration-200">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
        {Icon && (
          <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center", c.icon)}>
            <Icon size={15} />
          </div>
        )}
      </div>
      <p className={cn("text-3xl font-bold tabular-nums mt-1", c.value)}>{value}</p>
      {trend && <p className="text-xs text-gray-400 mt-0.5">{trend}</p>}
    </div>
  );
}
