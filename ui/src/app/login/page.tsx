import { signIn } from "@/auth"

export default function LoginPage() {
  return (
    <div className="flex h-screen w-full items-center justify-center bg-mesh">
      <div className="card w-[400px] p-8 text-center shadow-xl">
        <h1 className="text-2xl font-bold tracking-tight text-text-primary mb-2">DeployHub</h1>
        <p className="text-text-secondary mb-8">
          Authenticate to access your cloud environments
        </p>
        <form
          action={async () => {
            "use server"
            await signIn("auth0", { redirectTo: "/" })
          }}
        >
          <button type="submit" className="btn-primary w-full justify-center">
            Sign In with Auth0
          </button>
        </form>
      </div>
    </div>
  )
}
