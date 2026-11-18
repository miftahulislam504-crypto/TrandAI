"use server";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { rpc } from "@/lib/supabase";
import { buildCheck, parseBulk, type AdCheckInput } from "@/lib/adsparse";

const bdToday = () => new Date(Date.now() + 6 * 3600 * 1000).toISOString().slice(0, 10);

// ফেরার পথ শুধু /ads বা /products/<সংখ্যা>। অন্য কিছু এলে /ads (open redirect আটকাতে)
function safeBack(v: FormDataEntryValue | null): string {
  const s = String(v ?? "");
  return /^\/(ads|products\/\d+)$/.test(s) ? s : "/ads";
}

function go(back: string, ok: number, errors: string[]): never {
  const q = new URLSearchParams();
  if (ok > 0) q.set("ads_ok", String(ok));
  if (errors.length) q.set("ads_err", errors.slice(0, 6).join("\n").slice(0, 700));
  redirect(`${back}${q.toString() ? "?" + q.toString() : ""}`);
}

// একটা বা অনেক চেক সেভ। শুধু SQL ফাংশন record_ad_check ডাকে (Phase 6 migration লাগে)।
// bulk ঘরে লেখা থাকলে সেটা, নইলে একক ফর্মের ঘরগুলো। cid থাকলে চেকটা ওই প্রোডাক্টের নিজস্ব, নইলে প্রোডাক্টের ধরনের (segment)।
export async function saveAdChecks(formData: FormData) {
  const back = safeBack(formData.get("back"));
  const today = bdToday();
  const cidRaw = formData.get("cid");
  const cid = cidRaw ? Number(cidRaw) : null;
  if (cid !== null && (!Number.isInteger(cid) || cid <= 0)) go(back, 0, ["প্রোডাক্ট আইডি ঠিক নয়"]);

  const errors: string[] = [];
  const rows: { label: string; input: AdCheckInput }[] = [];
  const bulk = String(formData.get("bulk") ?? "");
  if (bulk.trim()) {
    const r = parseBulk(bulk, today);
    r.rows.forEach((x) => rows.push({ label: `লাইন ${x.line}`, input: x.input }));
    r.errors.forEach((e) => errors.push(`লাইন ${e.line} (${e.text}): ${e.message}`));
  } else {
    const r = buildCheck({
      keyword: String(formData.get("keyword") ?? ""), ads: String(formData.get("ads") ?? ""),
      advertisers: String(formData.get("advertisers") ?? ""), oldest: String(formData.get("oldest") ?? ""),
      new30: String(formData.get("new30") ?? ""),
    }, today);
    if (r.ok) rows.push({ label: r.input.keyword, input: r.input }); else errors.push(r.error);
  }

  const note = String(formData.get("note") ?? "").slice(0, 200);
  let ok = 0;
  for (const { label, input } of rows) {
    try {
      await rpc("record_ad_check", {
        p_keyword: input.keyword, p_active_ads: input.active_ads, p_advertisers: input.advertisers,
        p_oldest_start: input.oldest_start, p_new_30d: input.new_30d, p_canonical: cid, p_note: note || null, p_observed_on: null,
      });
      ok++;
    } catch (e) {
      const msg = (e as Error).message;
      errors.push(`${label}: ${/function .*record_ad_check|PGRST202|404/.test(msg) ? "Phase 6 migration (20261116000000_phase6.sql) চালাননি" : msg.replace(/^Supabase rpc record_ad_check: /, "")}`);
    }
  }
  revalidatePath("/ads");
  if (back !== "/ads") revalidatePath(back);
  go(back, ok, errors);
}

export async function deleteAdCheck(formData: FormData) {
  const back = safeBack(formData.get("back"));
  const id = Number(formData.get("id"));
  if (!Number.isInteger(id) || id <= 0) go(back, 0, ["চেক আইডি ঠিক নয়"]);
  try {
    await rpc("delete_ad_check", { p_id: id });
  } catch (e) {
    go(back, 0, [(e as Error).message]);
  }
  revalidatePath("/ads");
  if (back !== "/ads") revalidatePath(back);
  go(back, 0, []);
}
