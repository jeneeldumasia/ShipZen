"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import { Rocket, LayoutDashboard, FolderGit2, Zap, Activity, LogOut } from "lucide-react";
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
    <aside className="fixed inset-y-0 left-0 w-60 flex flex-col bg-white/10 dark:bg-black/20 backdrop-blur-xl border-r border-white/20 dark:border-white/10 shadow-[4px_0_24px_-12px_rgba(0,0,0,0.5)] z-30 transition-colors duration-300">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 py-5 border-b border-sidebar-border">
        <div className="w-8 h-8 rounded-lg bg-brand flex items-center justify-center shadow-glow">
          <Rocket size={16} className="text-canvas-bg" />
        </div>
        <div>
          <p className="text-sidebar-heading font-bold text-sm leading-none">ShipZen</p>
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

        {user?.is_admin && (
          <>
            <p className="section-title mt-6 mb-2">Admin Console</p>
            <Link href="/admin/projects" className={cn("nav-item", pathname.startsWith("/admin/projects") && "active")}>
              <FolderGit2 size={16} className="flex-shrink-0" />
              Global Projects
            </Link>
            <Link href="/admin/users" className={cn("nav-item", pathname.startsWith("/admin/users") && "active")}>
              <Activity size={16} className="flex-shrink-0" />
              User Management
            </Link>
            <Link href="/admin/audit" className={cn("nav-item", pathname.startsWith("/admin/audit") && "active")}>
              <Zap size={16} className="flex-shrink-0" />
              Global Audit Logs
            </Link>
          </>
        )}
      </nav>

      {/* Bottom */}
      <div className="px-3 py-4 border-t border-sidebar-border space-y-0.5">
        {user ? (
          <div className="flex items-center gap-2.5 px-3 py-2">
            {user.image ? (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={user.image as string} alt="Avatar" className="w-8 h-8 rounded-full shadow-sm border border-sidebar-border" />
              </>
            ) : (
              <div className="w-8 h-8 rounded-full bg-brand/20 flex items-center justify-center">
                <span className="text-xs font-bold text-brand">{user.name?.charAt(0) || user.email?.charAt(0) || "U"}</span>
              </div>
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sidebar-heading text-xs font-medium truncate">{user.name || "User"}</p>
              <p className="text-sidebar-text text-[11px] truncate">{user.email}</p>
            </div>
            <button onClick={() => signOut({ callbackUrl: "/login" })} className="text-sidebar-text hover:text-red-400 transition-colors">
              <LogOut size={16} />
            </button>
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
