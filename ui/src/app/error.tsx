'use client'; // Error components must be Client Components

import { useEffect } from 'react';
import { AlertCircle } from 'lucide-react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex h-[80vh] flex-col items-center justify-center space-y-4">
      <div className="rounded-full bg-red-500/10 p-4">
        <AlertCircle className="h-10 w-10 text-red-500" />
      </div>
      <h2 className="text-xl font-semibold text-text-primary">Something went wrong!</h2>
      <p className="text-text-secondary max-w-md text-center text-sm">
        An unexpected error occurred while loading this page. Our team has been notified.
      </p>
      <button
        onClick={() => reset()}
        className="mt-4 rounded-lg bg-canvas-border px-4 py-2 text-sm font-medium text-text-primary hover:bg-canvas-border/80 focus:outline-none focus:ring-2 focus:ring-brand focus:ring-offset-2 focus:ring-offset-canvas-bg transition-colors"
      >
        Try again
      </button>
    </div>
  );
}
