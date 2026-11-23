"use server";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { rpc } from "@/lib/supabase";
import { buildSignal } from "@/lib/signalparse";

const bdToday = () => new Date(Date.now() + 6 * 3600 * 1000).toISOString().slice(0, 10);

// ফেরার পথ একটাই: /signals। ফলাফল URL-এর ?sig_ok / ?sig_err দিয়ে দেখানো হয় (/ads-এর মতো)।
function go(ok: number, errors: string[]): never {
  const q = new URLSearchParams();
  if (ok > 0) q.set("sig_ok", String(ok));
  if (errors.length) q.set("sig_err", errors.slice(0, 4).join("\n").slice(0, 700));
  redirect(`/signals${q.toString() ? "?" + q.toString() : ""}`);
}

// একটা সিগন্যাল সেভ। শুধু SQL ফাংশন record_manual_signal ডাকে (Phase 11 migration লাগে)।
export async function saveSignal(formData: FormData) {
  const text = (k: string) => String(formData.get(k) ?? "");
  const r = buildSignal(
    { source: text("source"), keyword: text("keyword"), value: text("value"), unit: text("unit"), link: text("link"), note: text("note"), observed: text("observed") },
    bdToday(),
  );
  if (!r.ok) go(0, [r.error]);
  const i = r.input;
  try {
    await rpc("record_manual_signal", {
      p_source: i.source, p_keyword: i.keyword, p_value: i.value, p_unit: i.unit, p_link: i.link,
      p_note: i.note, p_canonical: null, p_observed_on: i.observed_on,
    });
  } catch (e) {
    const msg = (e as Error).message;
    go(0, [/function .*record_manual_signal|PGRST202|404/.test(msg)
      ? "Phase 11 migration (20261122000000_phase11.sql) চালাননি"
      : msg.replace(/^Supabase rpc record_manual_signal: /, "")]);
  }
  revalidatePath("/signals");
  go(1, []);
}

export async function deleteSignal(formData: FormData) {
  const id = Number(formData.get("id"));
  if (!Number.isInteger(id) || id <= 0) go(0, ["সিগন্যাল আইডি ঠিক নয়"]);
  try {
    await rpc("delete_manual_signal", { p_id: id });
  } catch (e) {
    go(0, [(e as Error).message]);
  }
  revalidatePath("/signals");
  go(0, []);
}
