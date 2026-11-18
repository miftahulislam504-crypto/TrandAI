import { NextRequest, NextResponse } from "next/server";
import { isAuthorized } from "@/lib/auth";

// সব পেজে HTTP Basic Auth। পাসওয়ার্ড সেট না থাকলে কিছুই দেখায় না (fail closed)।
export function middleware(req: NextRequest) {
  if (!process.env.DASHBOARD_PASSWORD) {
    return new NextResponse("DASHBOARD_PASSWORD সেট করা নেই", { status: 503 });
  }
  if (isAuthorized(req.headers.get("authorization"))) return NextResponse.next();
  return new NextResponse("লগইন দরকার", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Market Research", charset="UTF-8"' },
  });
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
