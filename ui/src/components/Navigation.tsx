import Link from "next/link";
import { auth, signOut } from "@/auth";
import { getBaseUrl } from "@/lib/api";
import { Terminal, LayoutDashboard, Settings, LogOut, UserRound } from "lucide-react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { NavLinks } from "@/components/NavLinks";

export async function Navigation() {
  const session = await auth();
  if (!session) return null;

  const token = (session as any).accessToken;
  let isAdmin = false;
  try {
    const res = await fetch(`${getBaseUrl()}/users/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store'
    });
    if (res.ok) {
      const data = await res.json();
      isAdmin = !!data.is_admin;
    }
  } catch (e) {}

  const user = session.user as any;
  const initials = user?.name
    ? user.name.split(" ").map((w: string) => w[0]).join("").toUpperCase().slice(0, 2)
    : user?.email?.[0]?.toUpperCase() ?? null;

  return (
    <div className="fixed top-5 left-1/2 -translate-x-1/2 z-50">
      <nav
        className="
          flex items-center gap-1 px-3 py-2 rounded-full
          bg-white/70 dark:bg-black/60
          border border-black/10 dark:border-white/10
          backdrop-blur-xl
          shadow-[0_8px_32px_rgba(0,0,0,0.15)] dark:shadow-[0_8px_32px_rgba(0,0,0,0.5)]
          text-sm
        "
      >
        {/* Logo */}
        <Link
          href="/"
          className="flex items-center gap-2 px-3 py-1.5 rounded-full font-bold tracking-tight text-text-primary hover:bg-canvas-border/20 transition-all mr-1"
          title="ShipZen"
        >
          <Terminal size={16} className="text-brand" />
          <span className="hidden sm:inline text-sm">ShipZen</span>
        </Link>

        <div className="w-px h-4 bg-canvas-border mx-1" />

        {/* Nav links */}
        <NavLinks isAdmin={isAdmin} />

        <div className="w-px h-4 bg-canvas-border mx-1" />

        {/* Theme toggle */}
        <ThemeToggle />

        <div className="w-px h-4 bg-canvas-border mx-1" />

        {/* User avatar + logout */}
        <div className="flex items-center gap-1">
          <div
            className="w-7 h-7 rounded-full bg-brand/10 dark:bg-brand/30 border border-brand/40 dark:border-brand/50 flex items-center justify-center text-[11px] font-bold text-brand"
            title={user?.email ?? "Signed in"}
          >
            {initials ?? <UserRound size={13} />}
          </div>
          <form
            action={async () => {
              "use server";
              await signOut({ redirectTo: "/login" });
            }}
          >
            <button
              type="submit"
              className="p-1.5 rounded-full text-text-secondary hover:text-text-primary hover:bg-canvas-border/30 transition-all"
              title={`Sign out (${user?.email})`}
            >
              <LogOut size={14} />
            </button>
          </form>
        </div>
      </nav>
    </div>
  );
}

