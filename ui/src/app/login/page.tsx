import { signIn } from "@/auth"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function LoginPage() {
  return (
    <div className="flex h-screen w-full items-center justify-center bg-gray-50/50">
      <Card className="w-[400px]">
        <CardHeader className="space-y-2 text-center">
          <CardTitle className="text-2xl font-bold tracking-tight">DeployHub</CardTitle>
          <CardDescription>
            Authenticate to access your cloud environments
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            action={async () => {
              "use server"
              await signIn("auth0", { redirectTo: "/" })
            }}
          >
            <Button type="submit" className="w-full">
              Sign In with Auth0
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
