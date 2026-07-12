export default function Loading() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="flex items-center justify-between">
        <div className="h-8 w-48 bg-canvas-border rounded"></div>
        <div className="h-10 w-32 bg-canvas-border rounded"></div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="col-span-2 space-y-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-24 bg-canvas-bg/50 rounded-xl border border-canvas-border"></div>
          ))}
        </div>
        <div className="h-96 bg-canvas-bg/50 rounded-xl border border-canvas-border"></div>
      </div>
    </div>
  );
}
