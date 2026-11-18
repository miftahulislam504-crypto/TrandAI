import { rpc } from "@/lib/supabase";
import { evaluateHealth, type Raw, type Status } from "@/lib/health";

export const dynamic = "force-dynamic";

const ICON: Record<Status, string> = { ok: "✅", warn: "⚠️", fail: "❌", na: "⚪" };
const OVERALL: Record<Status, string> = { ok: "সব ঠিক আছে", warn: "কিছু বিষয়ে নজর দিন", fail: "সমস্যা আছে", na: "এখনও যথেষ্ট ডেটা নেই" };

export default async function Health() {
  let raw: Raw | null = null;
  let error = "";
  try {
    raw = await rpc<Raw>("get_data_health", {});
  } catch (e) {
    const m = (e as Error).message;
    error = /PGRST202|404|function .*get_data_health/.test(m) ? "Phase 7 migration (20261117000000_phase7.sql) চালাননি" : m;
  }
  if (!raw) return (<><h1>🩺 Data Health</h1><p className="down">{error}</p></>);

  const { checks, overall } = evaluateHealth(raw);
  const groups = [...new Set(checks.map((c) => c.group))];
  const cats = Object.entries(raw.snapshots.listings_by_category);

  return (
    <>
      <h1>🩺 Data Health</h1>
      <p><b>{ICON[overall]} {OVERALL[overall]}</b> <span className="muted">· আজ {raw.today} (বাংলাদেশ)</span></p>
      {cats.length > 0 && <p className="muted">সক্রিয় listing: {cats.map(([k, n]) => `${k} ${n}`).join(" · ")}</p>}
      {groups.map((g) => (
        <div key={g} className="box" style={{ marginBottom: 10 }}>
          <h3>{g}</h3>
          {checks.filter((c) => c.group === g).map((c, i) => (
            <div key={i} className="review">
              <div>{ICON[c.status]} {c.label}</div>
              <div className="muted">{c.value}</div>
              {c.hint && <div className="muted">↳ {c.hint}</div>}
            </div>
          ))}
        </div>
      ))}
      <p className="muted">সীমাগুলো অনুমান (lib/health.ts-এর TH)। আসল চালানোর পর দরকারে বদলান।</p>
    </>
  );
}
