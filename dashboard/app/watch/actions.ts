"use server";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { rpc } from "@/lib/supabase";

// ফেরার পথ শুধু /watchlist, /alerts বা /products/<সংখ্যা>। অন্য কিছু এলে /watchlist (open redirect আটকাতে)
function safeBack(v: FormDataEntryValue | null): string {
  const s = String(v ?? "");
  return /^\/(watchlist|alerts|products\/\d+)$/.test(s) ? s : "/watchlist";
}

function fail(back: string, msg: string): never {
  const sep = back.includes("?") ? "&" : "?";
  redirect(`${back}${sep}watch_err=${encodeURIComponent(msg.slice(0, 300))}`);
}

// নজরে রাখা/ছাড়া। শুধু SQL ফাংশন set_watch ডাকে (Phase 7 migration লাগে)
export async function toggleWatch(formData: FormData) {
  const back = safeBack(formData.get("back"));
  const cid = Number(formData.get("cid"));
  if (!Number.isInteger(cid) || cid <= 0) fail(back, "প্রোডাক্ট আইডি ঠিক নয়");
  const on = formData.get("on") === "1";
  try {
    await rpc("set_watch", { p_canonical: cid, p_on: on, p_note: String(formData.get("note") ?? "").slice(0, 200) || null });
  } catch (e) {
    const m = (e as Error).message;
    fail(back, /PGRST202|404|function .*set_watch/.test(m) ? "Phase 7 migration (20261117000000_phase7.sql) চালাননি" : m.replace(/^Supabase rpc set_watch: /, ""));
  }
  revalidatePath("/watchlist");
  revalidatePath(back);
  redirect(back);
}

// ids ফাঁকা হলে সব না-দেখা অ্যালার্ট "দেখা হয়েছে"
export async function markAlertsSeen(formData: FormData) {
  const raw = String(formData.get("ids") ?? "").trim();
  let ids: number[] | null = null;
  if (raw) {
    ids = raw.split(",").map(Number);
    if (ids.length > 500 || ids.some((n) => !Number.isInteger(n) || n <= 0)) fail("/alerts", "অ্যালার্ট আইডি ঠিক নয়");
  }
  try {
    await rpc("mark_alerts_seen", { p_ids: ids });
  } catch (e) {
    fail("/alerts", (e as Error).message.replace(/^Supabase rpc mark_alerts_seen: /, ""));
  }
  revalidatePath("/alerts");
  revalidatePath("/");
  redirect("/alerts");
}
