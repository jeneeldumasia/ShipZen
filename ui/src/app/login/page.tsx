import { signIn } from "@/auth"
import Image from "next/image"

export const dynamic = "force-dynamic"

export default function LoginPage() {
  return (
    <div className="fixed inset-y-0 right-0 left-60 flex items-center justify-center overflow-hidden bg-black z-0">
      {/* Premium CSS Gradient Background instead of image */}
      <div className="absolute inset-0 z-0 bg-slate-950">
        <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/20 via-purple-500/10 to-transparent" />
        <div className="absolute top-0 -left-4 w-96 h-96 bg-purple-500 rounded-full mix-blend-multiply filter blur-[128px] opacity-40 animate-blob" />
        <div className="absolute top-0 -right-4 w-96 h-96 bg-indigo-500 rounded-full mix-blend-multiply filter blur-[128px] opacity-40 animate-blob" style={{ animationDelay: "2000ms" }} />
        <div className="absolute -bottom-8 left-20 w-96 h-96 bg-pink-500 rounded-full mix-blend-multiply filter blur-[128px] opacity-40 animate-blob" style={{ animationDelay: "4000ms" }} />
      </div>

      {/* Glassmorphism Card */}
      <div className="relative z-10 w-full max-w-[420px] rounded-2xl border border-white/10 bg-white/5 p-10 text-center shadow-2xl backdrop-blur-xl">
        <div className="mb-6 flex justify-center">
          {/* Logo Placeholder */}
          <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 shadow-lg">
            <svg
              className="h-8 w-8 text-white"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
        </div>

        <h1 className="mb-2 text-3xl font-extrabold tracking-tight text-white drop-shadow-md">
          ShipZen
        </h1>
        <p className="mb-8 text-sm font-medium text-slate-300">
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
            className="group relative flex w-full items-center justify-center overflow-hidden rounded-xl bg-white/10 px-4 py-3 text-sm font-semibold text-white transition-all duration-300 hover:bg-white/20 hover:shadow-[0_0_20px_rgba(139,92,246,0.3)] active:scale-[0.98]"
          >
            {/* Subtle highlight effect on hover */}
            <span className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/20 to-transparent transition-transform duration-500 ease-out group-hover:translate-x-full" />
            <span className="relative z-10 flex items-center gap-2">
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" />
              </svg>
              {process.env.GITHUB_CLIENT_ID || process.env.NODE_ENV === "production" ? "Continue with GitHub" : "Continue as Local Admin"}
            </span>
          </button>
        </form>
        
        <div className="mt-8 text-xs text-slate-400">
          Secure, enterprise-grade deployment platform.
        </div>
      </div>
    </div>
  )
}
