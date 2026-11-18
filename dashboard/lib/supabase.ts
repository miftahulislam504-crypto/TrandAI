import { headers } from "next/headers";
import { isAuthorized } from "@/lib/auth";

// শুধু সার্ভারে চলে। service_role key ব্রাউজারে যায় না।
export function assertAuthorized(): void {
  if (!isAuthorized(headers().get("authorization"))) throw new Error("Unauthorized");
}

function config() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;
  if (!url || !key) throw new Error("SUPABASE_URL ও SUPABASE_SERVICE_KEY সেট করুন");
  return { base: url.replace(/\/$/, "") + "/rest/v1", key };
}

export async function rest<T>(path: string, params: Record<string, string> = {}): Promise<T> {
  const { rows } = await restWithCount<T>(path, params, false);
  return rows;
}

export async function restWithCount<T>(
  path: string,
  params: Record<string, string> = {},
  count = true
): Promise<{ rows: T; total: number | null }> {
  assertAuthorized();
  const { base, key } = config();
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${base}/${path}${qs ? "?" + qs : ""}`, {
    headers: { apikey: key, Authorization: `Bearer ${key}`, ...(count ? { Prefer: "count=exact" } : {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Supabase ${path}: HTTP ${res.status}`);
  const range = res.headers.get("content-range"); // "0-49/312"
  const total = range && range.includes("/") ? Number(range.split("/")[1]) || null : null;
  return { rows: (await res.json()) as T, total };
}

// লেখার একমাত্র পথ: নির্দিষ্ট SQL ফাংশন (decide_match ইত্যাদি) ডাকা। সরাসরি টেবিলে লেখা হয় না।
export async function rpc<T = unknown>(fn: string, args: Record<string, unknown>): Promise<T> {
  assertAuthorized();
  const { base, key } = config();
  const res = await fetch(`${base}/rpc/${fn}`, {
    method: "POST",
    headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify(args),
    cache: "no-store",
  });
  if (!res.ok) {
    // SQL ফাংশনের raise exception-এর বার্তা (যেমন ভুল ইনপুটে বাংলা কারণ) PostgREST body-তে message হিসেবে আসে
    let detail = "";
    try { detail = String(((await res.json()) as { message?: string }).message ?? ""); } catch { /* body JSON নয় */ }
    throw new Error(`Supabase rpc ${fn}: HTTP ${res.status}${detail ? ": " + detail : ""}`);
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : null) as T;
}
