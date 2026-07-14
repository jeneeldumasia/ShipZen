import { LoginButton } from "@/components/LoginButton";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Link } from 'next-view-transitions';
import { Terminal } from "lucide-react";

export const dynamic = "force-dynamic";

export default function LandingPage() {
  const hasGithub = !!process.env.GITHUB_CLIENT_ID;

  return (
    <div className="flex flex-col min-h-screen bg-canvas-bg overflow-hidden relative selection:bg-brand/20 selection:text-text-primary">
      {/* Floating Glass Navigation */}
      <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50 w-full max-w-5xl px-4">
        <nav className="flex items-center justify-between px-4 py-3">
          <Link href="/" className="flex items-center gap-2 group">
            <Terminal size={18} className="text-brand" />
            <span className="font-sans font-bold text-sm tracking-tight text-text-primary">ShipZen</span>
          </Link>
          <ThemeToggle />
        </nav>
      </div>

      {/* Main Content */}
      <main className="flex-1 flex flex-col items-center justify-center relative z-10 px-4 pt-32 pb-16">
        
        {/* Typographic Story */}
        <div className="text-center max-w-3xl mx-auto mb-12 animate-fade-in" style={{ animationDuration: '0.8s', animationTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)' }}>
          <h1 className="text-5xl md:text-7xl font-sans font-semibold tracking-tighter mb-6 leading-[1.05] bg-clip-text text-transparent bg-gradient-to-br from-text-primary via-text-primary/90 to-text-secondary/70">
            Ship with absolute clarity.
          </h1>
          <p className="text-lg md:text-xl text-text-secondary font-sans tracking-tight max-w-xl mx-auto leading-relaxed">
            Fast shipping with complete peace of mind. A secure, enterprise-grade deployment platform designed to simplify your infrastructure.
          </p>
        </div>

        {/* Sleek Minimalist Auth Section (No Card) */}
        <div 
          className="w-full max-w-sm text-center animate-fade-in transition-transform duration-500 hover:scale-[1.02]"
          style={{ animationDuration: '1s', animationDelay: '150ms', animationFillMode: 'both', animationTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)' }}
        >
          <div className="mb-8">
            <h2 className="text-xl font-sans font-semibold text-text-primary tracking-tight mb-1">
              Start deploying
            </h2>
            <p className="text-xs text-text-secondary">
              Sign in to access your dashboard.
            </p>
          </div>

          <LoginButton hasGithub={hasGithub} />
        </div>
      </main>

      {/* Footer */}
      <footer className="w-full py-6 flex items-center justify-center text-xs text-text-secondary/60 font-sans z-10">
        © {new Date().getFullYear()} ShipZen. All rights reserved.
      </footer>
    </div>
  );
}
