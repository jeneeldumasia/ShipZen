import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: { default: "DeployHub", template: "%s · DeployHub" },
  description: "Internal Developer Platform",
};

import { auth } from "@/auth";

import { ThemeProvider } from "@/components/ThemeProvider";

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();

  return (
    <html lang="en" suppressHydrationWarning>
      <body className="bg-mesh min-h-screen antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <Sidebar user={session?.user} />
        {/* Content pushed right of the fixed sidebar */}
        <div className="pl-60 min-h-screen flex flex-col">
          <main className="flex-1 p-8 max-w-6xl w-full mx-auto animate-fade-in z-10 relative">
            {children}
          </main>
        </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
