import { NextResponse, type NextRequest } from "next/server";

// Server-side gate: pages need a session cookie; the API still checks every request itself.
const PUBLIC = ["/login", "/_next", "/favicon", "/api/"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLIC.some((p) => pathname.startsWith(p))) return NextResponse.next();
  if (!req.cookies.get("access_token") && !req.cookies.get("refresh_token")) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
