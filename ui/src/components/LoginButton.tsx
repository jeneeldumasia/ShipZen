"use client";

import { signIn } from "next-auth/react";
import { useState } from "react";

export function LoginButton({ hasGithub, isStubAuthEnabled }: { hasGithub: boolean; isStubAuthEnabled: boolean }) {
  const [isLoading, setIsLoading] = useState(false);

  const handleSignIn = async () => {
    setIsLoading(true);
    if (hasGithub) {
      await signIn("github", { callbackUrl: "/dashboard" });
    } else if (isStubAuthEnabled) {
      await signIn("credentials", { username: "admin", callbackUrl: "/dashboard" });
    }
  };

  const isConfigError = !hasGithub && !isStubAuthEnabled;

  return (
    <button
      onClick={handleSignIn}
      disabled={isLoading || isConfigError}
      className={`flex w-full items-center justify-center gap-2 rounded-xl px-5 py-3 text-sm font-bold uppercase tracking-widest transition-all ${
        isConfigError 
          ? "bg-red-500/10 text-red-500 cursor-not-allowed"
          : "bg-brand text-canvas-bg hover:-translate-y-0.5 hover:shadow-lg disabled:opacity-50"
      }`}
    >
      {isLoading ? (
        <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
      ) : isConfigError ? (
        <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
      ) : (
        <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" />
        </svg>
      )}
      {isConfigError ? "Config Error: Auth Missing" : hasGithub ? "Continue with GitHub" : "Continue as Local Admin"}
    </button>
  );
}
