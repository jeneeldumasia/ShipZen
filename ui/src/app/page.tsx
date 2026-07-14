import { LoginButton } from "@/components/LoginButton";
import { ThemeToggle } from "@/components/ThemeToggle";

export const dynamic = "force-dynamic";

export default function LandingPage() {
  const hasGithub = !!(process.env.GITHUB_CLIENT_ID || process.env.NODE_ENV === "production");

  return (
    <div className="flex min-h-screen bg-canvas-bg overflow-hidden relative">
      {/* Theme Toggle in Top Right */}
      <div className="absolute top-6 right-8 z-50">
        <ThemeToggle />
      </div>

      {/* LEFT SIDE: Marketing / Info */}
      <div className="hidden lg:flex w-1/2 flex-col justify-between p-12 border-r border-canvas-border/50 relative">
        {/* Subtle Background Glow */}
        <div className="pointer-events-none absolute inset-0 z-0 flex items-center justify-center opacity-30 dark:opacity-20">
          <div className="h-[40rem] w-[40rem] rounded-full bg-brand/10 blur-[100px]" />
        </div>

        <div className="relative z-10 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand shadow-md">
            <svg
              className="h-5 w-5 text-canvas-bg"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <span className="font-display font-bold text-xl tracking-tight">ShipZen</span>
        </div>

        <div className="relative z-10 max-w-lg mt-20">
          <h1 className="text-5xl font-display font-extrabold tracking-tight text-text-primary mb-6 leading-tight">
            Orchestrate your cloud environments with Zen.
          </h1>
          <p className="text-lg text-text-secondary mb-10 leading-relaxed font-medium">
            A secure, enterprise-grade deployment platform designed to simplify your infrastructure. 
            Automate deployments, enforce security gates, and gain real-time observability across all your projects.
          </p>

          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3 text-text-secondary">
              <svg className="h-5 w-5 text-brand" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              <span>Automated GitHub webhook integrations</span>
            </div>
            <div className="flex items-center gap-3 text-text-secondary">
              <svg className="h-5 w-5 text-brand" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              <span>Real-time deployment streaming</span>
            </div>
            <div className="flex items-center gap-3 text-text-secondary">
              <svg className="h-5 w-5 text-brand" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              <span>Synchronous ECR vulnerability scanning</span>
            </div>
          </div>
        </div>

        <div className="relative z-10 text-sm text-text-secondary font-medium">
          © {new Date().getFullYear()} Itara. All rights reserved.
        </div>
      </div>

      {/* RIGHT SIDE: Login Form */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-8 relative">
        <div className="w-full max-w-[400px]">
          {/* Logo for mobile only */}
          <div className="lg:hidden mb-12 flex justify-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-brand shadow-lg">
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

          <div className="text-center lg:text-left mb-10">
            <h2 className="text-3xl font-display font-bold text-text-primary tracking-tight mb-2">
              Welcome back
            </h2>
            <p className="text-text-secondary font-medium">
              Sign in to your account to continue.
            </p>
          </div>

          <LoginButton hasGithub={hasGithub} />
          
          <div className="mt-8 text-center text-xs font-semibold tracking-wide text-text-secondary/70 lg:hidden">
            Secure, enterprise-grade deployment platform.
          </div>
        </div>
      </div>
    </div>
  );
}
