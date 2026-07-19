import { handlers } from "@/auth"
import { NextRequest } from "next/server"

function withProxy(handler: any) {
  return (req: NextRequest) => {
    if (process.env.AUTH_URL?.startsWith("https://")) {
      const url = new URL(req.url)
      url.protocol = "https:"
      const headers = new Headers(req.headers)
      headers.set("x-forwarded-proto", "https")
      const newReq = new NextRequest(url.toString(), {
        headers,
        method: req.method,
        body: req.method === "POST" ? req.body : undefined,
        duplex: req.method === "POST" ? "half" : undefined,
      } as any)
      return handler(newReq)
    }
    return handler(req)
  }
}

export const GET = withProxy(handlers.GET)
export const POST = withProxy(handlers.POST)
