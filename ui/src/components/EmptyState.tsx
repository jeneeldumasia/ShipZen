import type { LucideIcon } from "lucide-react";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center rounded-xl border border-dashed border-slate-300 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/30 backdrop-blur-sm m-4">
      <div className="w-16 h-16 rounded-2xl bg-brand/10 flex items-center justify-center mb-4 shadow-inner ring-1 ring-brand/20">
        <Icon size={28} className="text-brand" />
      </div>
      <p className="text-base font-semibold text-text-primary">{title}</p>
      <p className="text-sm text-text-secondary mt-1 max-w-sm">{description}</p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
