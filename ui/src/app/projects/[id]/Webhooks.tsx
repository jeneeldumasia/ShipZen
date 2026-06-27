"use client";

import { Webhook, ExternalLink } from "lucide-react";

export function Webhooks() {
  const appSlug = process.env.NEXT_PUBLIC_GITHUB_APP_SLUG || "shipzen-jeneeldumasia";
  const installUrl = `https://github.com/apps/${appSlug}/installations/new`;

  return (
    <div className="card overflow-hidden mt-6">
      <div className="px-6 py-4 border-b border-canvas-border flex items-center gap-2">
        <Webhook size={16} className="text-text-secondary" />
        <h2 className="text-sm font-semibold text-text-primary">GitHub Integration</h2>
      </div>

      <div className="p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <p className="text-sm text-text-secondary">
              ShipZen uses a global GitHub App to automatically detect pushes to your repositories. 
              No per-repository configuration is required.
            </p>
          </div>
          <a
            href={installUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-primary flex items-center gap-2 whitespace-nowrap"
          >
            Manage GitHub App
            <ExternalLink size={16} />
          </a>
        </div>
      </div>
    </div>
  );
}
