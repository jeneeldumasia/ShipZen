import { PageHeader } from "@/components/PageHeader";
import { SystemControls } from "./SystemControls";

export default function AdminDashboardPage() {
  return (
    <div>
      <PageHeader 
        title="Admin Dashboard" 
        description="Global system administration and platform operations."
      />
      
      <div className="mt-8">
        <SystemControls />
      </div>
    </div>
  );
}
