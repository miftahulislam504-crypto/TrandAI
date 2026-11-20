import { rpc } from "@/lib/supabase";
import { evaluateHealth, type Raw, type Status } from "@/lib/health";
import { stripEmoji } from "@/lib/clean";
import { Icon, type IconName } from "../components/icons";

export const dynamic = "force-dynamic";

// রং ছাড়াও বোঝা যায়: আলাদা আইকন ও লেখা (ঠিক / নজর দিন / সমস্যা / ডেটা নেই)
const MARK: Record<Status, { icon: IconName; text: string }> = {
  ok: { icon: "check", text: "ঠিক" },
  warn: { icon: "alert", text: "নজর দিন" },
  fail: { icon: "close", text: "সমস্যা" },
  na: { icon: "info", text: "ডেটা নেই" },
};
const OVERALL: Record<Status, string> = { ok: "সব ঠিক আছে", warn: "কিছু বিষয়ে নজর দিন", fail: "সমস্যা আছে", na: "এখনও যথেষ্ট ডেটা নেই" };

function Mark({ s, lg }: { s: Status; lg?: boolean }) {
  return <span className={`status ${s}${lg ? " lg" : ""}`}><Icon name={MARK[s].icon} size={lg ? 16 : 14} />{lg ? OVERALL[s] : MARK[s].text}</span>;
}

export default async function Health() {
  let raw: Raw | null = null;
  let error = "";
  try {
    raw = await rpc<Raw>("get_data_health", {});
  } catch (e) {
    const m = (e as Error).message;
    error = /PGRST202|404|function .*get_data_health/.test(m) ? "Phase 7 migration (20261117000000_phase7.sql) চালাননি" : m;
  }
  if (!raw) {
    return (
      <>
        <h1>ডেটা হেলথ</h1>
        <div className="msg err" role="alert"><Icon name="alert" size={18} /><span>{error}</span></div>
      </>
    );
  }

  const { checks, overall } = evaluateHealth(raw);
  const groups = [...new Set(checks.map((c) => c.group))];
  const cats = Object.entries(raw.snapshots.listings_by_category);

  return (
    <>
      <h1>ডেটা হেলথ</h1>
      <p className="lede">আজ {raw.today} (বাংলাদেশ)</p>
      <p style={{ margin: "0 0 16px" }}><Mark s={overall} lg /></p>
      {cats.length > 0 && (
        <>
          <h2 style={{ marginTop: 0 }}>সক্রিয় listing</h2>
          <div className="chips" style={{ marginBottom: 16 }}>
            {cats.map(([k, n]) => <span key={k} className="chip">{k} {n}</span>)}
          </div>
        </>
      )}
      <div className="stack">
        {groups.map((g) => (
          <section key={g} className="box">
            <h3>{g}</h3>
            {checks.filter((c) => c.group === g).map((c, i) => (
              <div key={i} className="check">
                <div className="check-top"><span>{c.label}</span><Mark s={c.status} /></div>
                <div className="muted">{c.value}</div>
                {c.hint && <div className="muted">{stripEmoji(c.hint)}</div>}
              </div>
            ))}
          </section>
        ))}
      </div>
      <p className="hint">সীমাগুলো অনুমান (<code>lib/health.ts</code>-এর TH)। আসল চালানোর পর দরকারে বদলান।</p>
    </>
  );
}
