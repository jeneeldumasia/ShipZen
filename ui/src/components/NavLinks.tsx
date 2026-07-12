"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Settings, FolderGit2 } from "lucide-react";

export function NavLinks({ isAdmin }: { isAdmin?: boolean }) {
  const pathname = usePathname();

  return (
    <>
      <NavPill href="/" icon={<LayoutDashboard size={15} />} label="Dashboard" active={pathname === "/"} />
      <NavPill href="/projects" icon={<FolderGit2 size={15} />} label="Projects" active={pathname.startsWith("/projects")} />
      {isAdmin && <NavPill href="/admin" icon={<Settings size={15} />} label="Admin" active={pathname.startsWith("/admin")} />}
    </>
  );
}

function NavPill({ href, icon, label, active }: { href: string; icon: React.ReactNode; label: string; active?: boolean }) {
  return (
    <Link
      href={href}
      className={`group flex items-center gap-2 px-3 py-1.5 rounded-full transition-all ${
        active 
          ? "bg-canvas-border/40 text-text-primary shadow-sm" 
          : "text-text-secondary hover:text-text-primary hover:bg-canvas-border/20"
      }`}
      title={label}
    >
      {icon}
      <span className="hidden sm:inline text-xs font-medium">{label}</span>
    </Link>
  );
}
