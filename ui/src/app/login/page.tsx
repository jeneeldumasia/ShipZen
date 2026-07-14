import { signIn } from "@/auth"

export const dynamic = "force-dynamic"

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas-bg p-4">
      <div className="w-full max-w-[420px] border border-canvas-border bg-canvas-card p-10 text-center shadow-none">
        <div className="mb-8 flex justify-center">
          <div className="flex h-16 w-16 items-center justify-center border border-canvas-border bg-canvas-bg">
            <svg
              className="h-8 w-8 text-text-primary"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
        </div>

        <h1 className="mb-2 font-display text-3xl font-extrabold uppercase tracking-tight text-text-primary">
          ShipZen
        </h1>
        <p className="mb-10 text-sm font-medium text-text-secondary">
          Sign in to orchestrate your cloud environments.
        </p>

        <form
          action={async () => {
            "use server"
            if (process.env.GITHUB_CLIENT_ID || process.env.NODE_ENV === "production") {
              await signIn("github", { redirectTo: "/" })
            } else {
              await signIn("credentials", { username: "admin", redirectTo: "/" })
            }
          }}
        >
          <button
            type="submit"
            className="btn-primary w-full"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" />
            </svg>
            {process.env.GITHUB_CLIENT_ID || process.env.NODE_ENV === "production" ? "Continue with GitHub" : "Continue as Local Admin"}
          </button>
        </form>
        
        <div className="mt-8 text-xs font-bold uppercase tracking-widest text-text-secondary">
          Secure, enterprise-grade deployment platform.
        </div>
      </div>
    </div>
  )
}
