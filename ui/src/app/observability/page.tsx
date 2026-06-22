import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";

export const metadata = { title: "Platform Health" };

export default function ObservabilityPage() {
  const grafanaUrl = "https://grafana-shipzen.jeneeldumasia.codes/d/platform-health?orgId=1&kiosk=tv";

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary mb-6 group w-fit">
        <ArrowLeft size={14} className="group-hover:-translate-x-0.5 transition-transform" />
        Dashboard
      </Link>

      <PageHeader
        title="Platform Health"
        description="Global observability and metrics"
        actions={
          <a
            href="https://grafana-shipzen.jeneeldumasia.codes"
            target="_blank"
            rel="noopener noreferrer"
            className="btn-secondary"
          >
            <ExternalLink size={15} />
            Open Grafana
          </a>
        }
      />

      <div className="flex-1 card overflow-hidden mt-4">
        <iframe
          src={grafanaUrl}
          className="w-full h-full border-0"
          title="Grafana Platform Health Dashboard"
          sandbox="allow-same-origin allow-scripts"
        />
      </div>
    </div>
  );
}
