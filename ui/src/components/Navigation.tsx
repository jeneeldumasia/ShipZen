import Link from "next/link";
import { auth, signOut } from "@/auth";
import { Terminal, FolderGit2, LogOut, Settings, LayoutDashboard } from "lucide-react";

export async function Navigation() {
  const session = await auth();
  if (!session) return null; // Don't show navigation on login page

  const user = session.user as any;
  // We don't fetch role here to avoid double-fetching in layout, we just assume basic layout.
  // Or we can just render the links. We know user.email from session.

  return (
    <div className="fixed top-0 left-0 right-0 h-16 z-40 flex items-center justify-between px-8 bg-black/20 backdrop-blur-md border-b border-white/5">
      <div className="flex items-center gap-6">
        <Link href="/" className="flex items-center gap-2 text-white font-display font-bold text-lg tracking-tight hover:text-brand transition-colors">
          <Terminal size={20} className="text-brand" />
          ShipZen
        </Link>
        <div className="h-4 w-px bg-white/10" />
        <Link href="/" className="text-sm font-medium text-zinc-400 hover:text-white transition-colors flex items-center gap-2">
          <LayoutDashboard size={16} />
          Dashboard
        </Link>
        <Link href="/admin" className="text-sm font-medium text-zinc-400 hover:text-white transition-colors flex items-center gap-2">
          <Settings size={16} />
          Admin Console
        </Link>
      </div>

      <div className="flex items-center gap-4">
        <div className="text-sm text-zinc-500 font-mono">
          {user?.email}
        </div>
        <form action={async () => {
          "use server";
          await signOut({ redirectTo: "/login" });
        }}>
          <button type="submit" className="p-2 text-zinc-400 hover:text-white hover:bg-white/5 rounded-lg transition-all" title="Sign Out">
            <LogOut size={16} />
          </button>
        </form>
      </div>
    </div>
  );
}
