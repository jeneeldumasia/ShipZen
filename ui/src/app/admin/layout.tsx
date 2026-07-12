import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { getBaseUrl } from "@/lib/api";
import { AdminSidebar } from "./AdminSidebar";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session) {
    redirect("/login");
  }

  const token = (session as any).accessToken;
  
  // Verify admin status
  try {
    const res = await fetch(`${getBaseUrl()}/users/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store'
    });
    if (res.ok) {
      const data = await res.json();
      if (!data.is_admin) {
        redirect("/");
      }
    } else {
      redirect("/");
    }
  } catch (e) {
    redirect("/");
  }

  return (
    <div className="flex flex-col md:flex-row gap-8">
      {/* Admin Sidebar */}
      <AdminSidebar />

      {/* Admin Content */}
      <div className="flex-1 min-w-0">
        {children}
      </div>
    </div>
  );
}
