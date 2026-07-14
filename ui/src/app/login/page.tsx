import { LoginButton } from "./LoginButton";
import { ThemeToggle } from "@/components/ThemeToggle";

export const dynamic = "force-dynamic"

export default function LoginPage() {
  const hasGithub = !!(process.env.GITHUB_CLIENT_ID || process.env.NODE_ENV === "production");

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-canvas-bg p-4 overflow-hidden">
      {/* Zen Theme Toggle */}
      <div className="absolute top-6 right-8">
        <ThemeToggle />
      </div>

      {/* Subtle Zen Background Glows */}
      <div className="pointer-events-none absolute inset-0 z-0 flex items-center justify-center opacity-30 dark:opacity-20">
        <div className="h-[40rem] w-[40rem] rounded-full bg-brand/10 blur-[100px]" />
      </div>

      <div className="relative z-10 w-full max-w-[400px] rounded-2xl border border-canvas-border/50 bg-canvas-card p-10 text-center shadow-2xl backdrop-blur-sm transition-all">
        <div className="mb-8 flex justify-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-brand/90 to-brand shadow-lg">
            <svg
              className="h-8 w-8 text-canvas-bg"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
        </div>

        <h1 className="mb-2 font-display text-3xl font-extrabold tracking-tight text-text-primary">
          ShipZen
        </h1>
        <p className="mb-10 text-sm font-medium text-text-secondary">
          Sign in to orchestrate your cloud environments.
        </p>

        <LoginButton hasGithub={hasGithub} />
        
        <div className="mt-8 text-xs font-semibold tracking-wide text-text-secondary/70">
          Secure, enterprise-grade deployment platform.
        </div>
      </div>
    </div>
  )
}
