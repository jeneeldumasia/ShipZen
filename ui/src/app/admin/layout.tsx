"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Settings, FolderGit2, Server, Users, ShieldAlert } from "lucide-react";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  const navItems = [
    { name: "System", href: "/admin", icon: Settings },
    { name: "Projects", href: "/admin/projects", icon: FolderGit2 },
    { name: "Deployments", href: "/admin/deployments", icon: Server },
    { name: "Users", href: "/admin/users", icon: Users },
    { name: "Audit Logs", href: "/admin/audit", icon: ShieldAlert },
  ];

  return (
    <div className="flex flex-col md:flex-row gap-8">
      {/* Admin Sidebar */}
      <div className="w-full md:w-64 shrink-0">
        <div className="sticky top-24 flex flex-col gap-1 bg-canvas-card border border-canvas-border/50 p-4 rounded-xl">
          <div className="px-4 pb-4 mb-2 border-b border-canvas-border">
            <h2 className="text-lg font-bold text-text-primary tracking-tight">Admin Console</h2>
          </div>
          {navItems.map((item) => {
            const isActive = pathname === item.href;
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-brand/10 text-brand"
                    : "text-text-secondary hover:text-text-primary hover:bg-canvas-border/20"
                }`}
              >
                <Icon size={18} />
                {item.name}
              </Link>
            );
          })}
        </div>
      </div>

      {/* Admin Content */}
      <div className="flex-1 min-w-0">
        {children}
      </div>
    </div>
  );
}
