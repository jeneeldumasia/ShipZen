"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Refreshes the current page every `intervalMs` milliseconds.
 * Used on the deployment detail page while a deployment is in-progress
 * so state transitions (Queued → Building → Running) show up without
 * the user manually refreshing.
 */
export function AutoRefresh({ intervalMs }: { intervalMs: number }) {
  const router = useRouter();

  useEffect(() => {
    const id = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(id);
  }, [router, intervalMs]);

  return null;
}
