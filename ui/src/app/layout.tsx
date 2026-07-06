import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: { default: "ShipZen", template: "%s · ShipZen" },
  description: "Internal Developer Platform",
};

import { auth } from "@/auth";

import { ThemeProvider } from "@/components/ThemeProvider";
import { CommandPalette } from "@/components/CommandPalette";
import { Toaster } from "sonner";

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  
  let userWithRole = session?.user as any;
  if (session && (session as { accessToken?: string }).accessToken) {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/users/me`, {
        headers: { Authorization: `Bearer ${(session as { accessToken?: string }).accessToken}` },
        cache: 'no-store'
      });
      if (res.ok) {
        const data = await res.json();
        userWithRole = { ...userWithRole, is_admin: data.is_admin };
      }
    } catch (e) {
      console.error("Failed to fetch user role", e);
    }
  }

  return (
    <html lang="en" suppressHydrationWarning>
      <body className="bg-mesh min-h-screen antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <Sidebar user={userWithRole} />
        {/* Content pushed right of the fixed sidebar */}
        <div className="pl-60 min-h-screen flex flex-col">
          <main className="flex-1 p-8 max-w-6xl w-full mx-auto animate-fade-in z-10 relative">
            {children}
          </main>
        </div>
          <CommandPalette />
          <Toaster position="bottom-right" theme="system" />
        </ThemeProvider>
      </body>
    </html>
  );
}
