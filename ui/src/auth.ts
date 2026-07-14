import NextAuth from "next-auth"
import GitHubProvider from "next-auth/providers/github"
import CredentialsProvider from "next-auth/providers/credentials"

// Use GitHub if configured, otherwise use Stub Credentials
const providers = []

const githubClientId = process.env.GITHUB_CLIENT_ID || process.env.SHIPZEN_GITHUB_CLIENT_ID;
const githubClientSecret = process.env.GITHUB_CLIENT_SECRET || process.env.SHIPZEN_GITHUB_CLIENT_SECRET;

if (githubClientId && githubClientSecret) {
  providers.push(
    GitHubProvider({
      clientId: githubClientId,
      clientSecret: githubClientSecret,
      checks: ["none"],
    })
  )
} else if (process.env.NODE_ENV !== "production") {
  // Local Dev / Missing Auth0 fallback
  providers.push(
    CredentialsProvider({
      name: "Stub Auth",
      credentials: {
        username: { label: "Username", type: "text", placeholder: "admin" },
      },
      async authorize(credentials) {
        return {
          id: "local-dev-user",
          name: (credentials as Record<string, string>)?.username || "Local Admin",
          email: "admin@shipzen.local",
          image: "https://api.dicebear.com/7.x/avataaars/svg?seed=admin"
        }
      }
    })
  )
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers,
  secret: process.env.AUTH_SECRET || process.env.SHIPZEN_AUTH_SECRET,
  trustHost: true,
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        token.accessToken = account.access_token || "stub-token"
      }
      return token
    },
    async session({ session, token }) {
      // @ts-expect-error custom property
      session.accessToken = token.accessToken
      return session
    },
  },
  pages: {
    signIn: "/",
  },
})
