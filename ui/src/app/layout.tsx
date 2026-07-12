import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: { default: "ShipZen", template: "%s · ShipZen" },
  description: "Internal Developer Platform",
};

import { auth } from "@/auth";

import { ThemeProvider } from "@/components/ThemeProvider";
import { CommandPalette } from "@/components/CommandPalette";
import { Navigation } from "@/components/Navigation";
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
          <Navigation />
          {/* Pure Canvas Layout */}
          <div className="w-full min-h-screen flex flex-col items-center pt-24 px-8">
            <main className="flex-1 w-full max-w-5xl animate-fade-in z-10 relative">
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
