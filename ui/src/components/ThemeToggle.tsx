"use client";

import * as React from "react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

export function ThemeToggle() {
  const { setTheme, theme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  // Avoid hydration mismatch
  React.useEffect(() => setMounted(true), []);
  
  if (!mounted) {
    return <div className="h-10 w-[72px] rounded-full bg-canvas-card animate-pulse" />;
  }

  const isDark = resolvedTheme === "dark";

  return (
    <button
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="group relative flex h-10 w-[72px] items-center rounded-full bg-canvas-card border border-canvas-border/60 shadow-sm transition-colors hover:border-brand/50 focus:outline-none focus:ring-2 focus:ring-brand/50"
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      <div 
        className={`absolute left-1 flex h-8 w-8 items-center justify-center rounded-full bg-canvas-bg shadow-sm transition-transform duration-500 ease-[cubic-bezier(0.2,0.8,0.2,1)] ${isDark ? "translate-x-0" : "translate-x-8"}`}
      >
        <Moon 
          size={16} 
          className={`absolute text-text-primary transition-all duration-500 ${isDark ? "scale-100 opacity-100 rotate-0" : "scale-50 opacity-0 -rotate-90"}`} 
        />
        <Sun 
          size={16} 
          className={`absolute text-text-primary transition-all duration-500 ${isDark ? "scale-50 opacity-0 rotate-90" : "scale-100 opacity-100 rotate-0"}`} 
        />
      </div>
      <div className="absolute inset-0 flex items-center justify-between px-2.5 pointer-events-none">
        <Moon size={14} className={`text-text-secondary transition-opacity duration-300 ${isDark ? "opacity-0" : "opacity-40"}`} />
        <Sun size={14} className={`text-text-secondary transition-opacity duration-300 ${isDark ? "opacity-40" : "opacity-0"}`} />
      </div>
    </button>
  );
}
