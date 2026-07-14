import { auth } from "@/auth"

export default auth((req) => {
  const isAuth = !!req.auth;
  const isPublicPage = req.nextUrl.pathname === "/";
  
  if (!isAuth && !isPublicPage) {
    const newUrl = new URL("/", req.nextUrl.origin)
    return Response.redirect(newUrl)
  }

  if (isAuth && isPublicPage) {
    const newUrl = new URL("/dashboard", req.nextUrl.origin)
    return Response.redirect(newUrl)
  }
})

// Optionally, don't invoke Middleware on some paths
export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|devops_bg.png).*)"],
}
