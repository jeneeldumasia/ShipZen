"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Rocket, LayoutDashboard, FolderGit2, Zap, Activity } from "lucide-react";
import { cn } from "@/lib/cn";
import { ThemeToggle } from "./ThemeToggle";

const NAV = [
  { href: "/",                 label: "Dashboard",     icon: LayoutDashboard },
  { href: "/projects",         label: "Projects",      icon: FolderGit2 },
  { href: "/observability",    label: "Platform Health", icon: Activity },
];

export function Sidebar({ user }: { user?: any }) {
  const pathname = usePathname();

  return (
    <aside className="fixed inset-y-0 left-0 w-60 flex flex-col bg-sidebar-bg/90 backdrop-blur-xl border-r border-sidebar-border shadow-[4px_0_24px_-12px_rgba(0,0,0,0.5)] z-30 transition-colors duration-300">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 py-5 border-b border-sidebar-border">
        <div className="w-8 h-8 rounded-lg bg-brand flex items-center justify-center shadow-glow">
          <Rocket size={16} className="text-white" />
        </div>
        <div>
          <p className="text-sidebar-heading font-bold text-sm leading-none">DeployHub</p>
          <p className="text-sidebar-text text-xs mt-0.5">Platform v1.0</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        <p className="section-title mt-1 mb-2">Navigation</p>
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn("nav-item", active && "active")}
            >
              <Icon size={16} className="flex-shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Bottom */}
      <div className="px-3 py-4 border-t border-sidebar-border space-y-0.5">
        {user ? (
          <div className="flex items-center gap-2.5 px-3 py-2">
            {user.image ? (
              <img src={user.image} alt="Avatar" className="w-8 h-8 rounded-full shadow-sm border border-sidebar-border" />
            ) : (
              <div className="w-8 h-8 rounded-full bg-brand/20 flex items-center justify-center">
                <span className="text-xs font-bold text-brand">{user.name?.charAt(0) || user.email?.charAt(0) || "U"}</span>
              </div>
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sidebar-heading text-xs font-medium truncate">{user.name || "User"}</p>
              <p className="text-sidebar-text text-[11px] truncate">{user.email}</p>
            </div>
            <ThemeToggle />
          </div>
        ) : (
          <div className="flex items-center gap-2.5 px-3 py-2">
            <div className="w-7 h-7 rounded-full bg-brand/20 flex items-center justify-center">
              <Zap size={13} className="text-brand-muted" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sidebar-heading text-xs font-medium truncate">Connected</p>
              <p className="text-sidebar-text text-xs truncate">API · Redis · Postgres</p>
            </div>
            <ThemeToggle />
          </div>
        )}
      </div>
    </aside>
  );
}
