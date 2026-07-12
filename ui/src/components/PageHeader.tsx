import { cn } from "@/lib/cn";

export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 mb-8", className)}>
      <div>
        <h1 className="text-3xl font-display font-bold text-text-primary tracking-tight uppercase">{title}</h1>
        {description && (
          <div className="text-sm text-text-secondary mt-2">{description}</div>
        )}
      </div>
      {actions && <div className="flex items-center gap-2 flex-shrink-0">{actions}</div>}
    </div>
  );
}
