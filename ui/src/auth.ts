import NextAuth from "next-auth"
import Auth0Provider from "next-auth/providers/auth0"

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Auth0Provider({
      clientId: process.env.AUTH0_CLIENT_ID,
      clientSecret: process.env.AUTH0_CLIENT_SECRET,
      issuer: process.env.AUTH0_ISSUER, // Typically https://<your-tenant>.auth0.com
      authorization: {
        params: {
          audience: process.env.AUTH0_AUDIENCE, // The API audience so we get a JWT access token
        },
      },
    }),
  ],
  callbacks: {
    async jwt({ token, account }) {
      // Persist the OAuth access_token right after signin
      if (account) {
        token.accessToken = account.access_token
      }
      return token
    },
    async session({ session, token }) {
      // Send properties to the client, like an access_token from a provider.
      // @ts-ignore
      session.accessToken = token.accessToken
      return session
    },
  },
  pages: {
    signIn: "/api/auth/signin",
  },
})
