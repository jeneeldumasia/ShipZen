import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        sidebar: {
          bg:      "var(--sidebar-bg)",
          border:  "var(--sidebar-border)",
          hover:   "var(--sidebar-hover)",
          active:  "var(--sidebar-active)",
          text:    "var(--sidebar-text)",
          heading: "var(--sidebar-heading)",
        },
        canvas: {
          bg:     "var(--canvas-bg)",
          card:   "var(--canvas-card)",
          border: "var(--canvas-border)",
        },
        brand: {
          DEFAULT: "var(--brand-default)",
          hover:   "var(--brand-hover)",
          light:   "var(--brand-light)",
          muted:   "var(--brand-muted)",
        },
        status: {
          running:     "#10b981",
          building:    "#3b82f6",
          queued:      "#94a3b8",
          failed:      "#ef4444",
          terminating: "#f97316",
          retry:       "#f59e0b",
          dlq:         "#dc2626",
          verifying:   "#8b5cf6",
          deploying:   "#06b6d4",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card:  "0 4px 20px -2px rgba(0, 0, 0, 0.05)",
        "card-hover": "0 8px 30px -4px rgba(0, 0, 0, 0.1)",
        glow:  "0 0 20px -4px var(--brand-glow)",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "slide-in":   "slideIn 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
        "fade-in":    "fadeIn 0.4s ease-out",
        "float":      "float 6s ease-in-out infinite",
        "mesh-shift": "meshShift 15s ease-in-out infinite alternate",
      },
      keyframes: {
        slideIn: {
          "0%":   { transform: "translateY(10px)", opacity: "0" },
          "100%": { transform: "translateY(0)",    opacity: "1" },
        },
        fadeIn: {
          "0%":   { opacity: "0" },
          "100%": { opacity: "1" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%":      { transform: "translateY(-5px)" },
        },
        meshShift: {
          "0%": { backgroundPosition: "0% 50%" },
          "100%": { backgroundPosition: "100% 50%" },
        }
      },
    },
  },
  plugins: [],
};

export default config;
