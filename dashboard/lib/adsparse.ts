// Facebook Ads Library চেকের ইনপুট পার্সিং ও যাচাই (বিশুদ্ধ ফাংশন, নেটওয়ার্ক ছাড়া)।
// ফোনে টাইপ করা সহজ করতে: বাংলা অঙ্ক, "1,200", "~120", "3 Oct 2026", "3/10/2026" সব চলে।
// যাচাইয়ের নিয়ম SQL ফাংশন record_ad_check-এর সাথে মেলানো, যাতে ভুল ইনপুটে আগেই বাংলা বার্তা পাওয়া যায়।

export type AdCheckInput = {
  keyword: string;
  active_ads: number;
  advertisers: number | null;
  oldest_start: string | null; // YYYY-MM-DD
  new_30d: number | null;
};

export type Parsed = { ok: true; input: AdCheckInput } | { ok: false; error: string };

const BN = "০১২৩৪৫৬৭৮৯";
export function normDigits(s: string): string {
  return s.replace(/[০-৯]/g, (c) => String(BN.indexOf(c)));
}

const MONTHS: Record<string, number> = {
  jan: 1, january: 1, feb: 2, february: 2, mar: 3, march: 3, apr: 4, april: 4, may: 5, jun: 6, june: 6,
  jul: 7, july: 7, aug: 8, august: 8, sep: 9, sept: 9, september: 9, oct: 10, october: 10, nov: 11, november: 11, dec: 12, december: 12,
};

const pad = (n: number) => String(n).padStart(2, "0");

function validYmd(y: number, m: number, d: number): string | null {
  if (!Number.isInteger(y) || !Number.isInteger(m) || !Number.isInteger(d)) return null;
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null; // ৩১ ফেব্রুয়ারি ইত্যাদি
  return `${y}-${pad(m)}-${pad(d)}`;
}

// ফাঁকা বা "-" হলে null (দেওয়া হয়নি)। ভুল হলে Error। চেকের তারিখের (today) পরের বা ২০১৮-র আগের তারিখ গ্রহণযোগ্য নয়।
export function parseDate(raw: string, today: string): string | null {
  const s = normDigits(raw).trim().replace(/\s+/g, " ").replace(/,/g, "");
  if (s === "" || s === "-" || s === "–") return null;
  let iso: string | null = null;
  let m: RegExpMatchArray | null;
  if ((m = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/))) iso = validYmd(+m[1], +m[2], +m[3]);
  else if ((m = s.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/))) iso = validYmd(+m[3], +m[2], +m[1]); // দিন/মাস/বছর
  else if ((m = s.match(/^(\d{1,2}) ([A-Za-z]+) (\d{4})$/)) && MONTHS[m[2].toLowerCase()]) iso = validYmd(+m[3], MONTHS[m[2].toLowerCase()], +m[1]);
  else if ((m = s.match(/^([A-Za-z]+) (\d{1,2}) (\d{4})$/)) && MONTHS[m[1].toLowerCase()]) iso = validYmd(+m[3], MONTHS[m[1].toLowerCase()], +m[2]);
  if (!iso) throw new Error(`তারিখ বোঝা যায়নি: "${raw.trim()}" (লিখুন 2026-10-03 বা 3/10/2026 বা 3 Oct 2026)`);
  if (iso > today) throw new Error(`তারিখ ভবিষ্যতের হতে পারে না: ${iso}`);
  if (iso < "2018-01-01") throw new Error(`তারিখ ২০১৮-র আগের: ${iso}`);
  return iso;
}

// ফাঁকা বা "-" হলে null। "~120", "120+", "1,200" চলে। ভগ্নাংশ বা ঋণাত্মক হলে Error।
export function parseCount(raw: string, label: string): number | null {
  const s = normDigits(raw).trim().replace(/^[~≈]/, "").replace(/\+$/, "").replace(/,/g, "").trim();
  if (s === "" || s === "-" || s === "–") return null;
  if (!/^\d{1,7}$/.test(s)) throw new Error(`${label} একটা অ-ঋণাত্মক পূর্ণসংখ্যা হতে হবে: "${raw.trim()}"`);
  return Number(s);
}

export function buildCheck(f: { keyword: string; ads: string; advertisers?: string; oldest?: string; new30?: string }, today: string): Parsed {
  try {
    const keyword = f.keyword.trim().replace(/\s+/g, " ");
    if (keyword.length < 1 || keyword.length > 80) return { ok: false, error: "শব্দ ১–৮০ অক্ষরের হতে হবে" };
    const active = parseCount(f.ads, "বিজ্ঞাপন সংখ্যা");
    if (active === null) return { ok: false, error: "বিজ্ঞাপন সংখ্যা দিতে হবে (০ হলে ০ লিখুন)" };
    const advertisers = parseCount(f.advertisers ?? "", "বিজ্ঞাপনদাতা");
    const oldest = parseDate(f.oldest ?? "", today);
    const new30 = parseCount(f.new30 ?? "", "গত ৩০ দিনের নতুন বিজ্ঞাপন");
    if (advertisers !== null && advertisers > active) return { ok: false, error: "বিজ্ঞাপনদাতা সংখ্যা বিজ্ঞাপন সংখ্যার বেশি হতে পারে না" };
    if (new30 !== null && new30 > active) return { ok: false, error: "গত ৩০ দিনের নতুন বিজ্ঞাপন মোট বিজ্ঞাপনের বেশি হতে পারে না" };
    if (active === 0 && ((advertisers ?? 0) > 0 || oldest !== null || (new30 ?? 0) > 0)) {
      return { ok: false, error: "বিজ্ঞাপন ০ হলে বিজ্ঞাপনদাতা, শুরুর তারিখ বা নতুন বিজ্ঞাপন দেওয়া যায় না" };
    }
    return { ok: true, input: { keyword, active_ads: active, advertisers, oldest_start: oldest, new_30d: new30 } };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
}

// এক লাইন: শব্দ | বিজ্ঞাপন | বিজ্ঞাপনদাতা | সবচেয়ে পুরনোর তারিখ | গত ৩০ দিনে নতুন (শেষের তিনটা বাদ দেওয়া যায়, ফাঁকা বা "-" দিলেও চলে)।
// | বা ট্যাব থাকলে সেটা দিয়ে, না থাকলে কমা দিয়ে ভাগ হয় (কমা দিলে সংখ্যায় হাজারের কমা চলবে না)।
export function parseLine(line: string, today: string): Parsed {
  const sep = /[|\t]/.test(line) ? /[|\t]/ : /,/;
  const parts = line.split(sep).map((x) => x.trim());
  if (parts.length < 2) return { ok: false, error: "কমপক্ষে শব্দ ও বিজ্ঞাপন সংখ্যা লাগে (শব্দ | সংখ্যা)" };
  if (parts.length > 5) return { ok: false, error: "সর্বোচ্চ ৫টা ঘর: শব্দ | বিজ্ঞাপন | বিজ্ঞাপনদাতা | পুরনোর তারিখ | নতুন-৩০ দিন" };
  return buildCheck({ keyword: parts[0], ads: parts[1], advertisers: parts[2], oldest: parts[3], new30: parts[4] }, today);
}

export type BulkResult = {
  rows: { line: number; input: AdCheckInput }[];
  errors: { line: number; text: string; message: string }[];
};

export const MAX_BULK_LINES = 60;

export function parseBulk(text: string, today: string): BulkResult {
  const out: BulkResult = { rows: [], errors: [] };
  const lines = text.split(/\r?\n/);
  let used = 0;
  lines.forEach((raw, i) => {
    const line = raw.trim();
    if (line === "" || line.startsWith("#")) return;
    used++;
    if (used > MAX_BULK_LINES) {
      if (used === MAX_BULK_LINES + 1) out.errors.push({ line: i + 1, text: line.slice(0, 60), message: `একবারে সর্বোচ্চ ${MAX_BULK_LINES}টা লাইন, বাকিগুলো আলাদাভাবে দিন` });
      return;
    }
    const r = parseLine(line, today);
    if (r.ok) out.rows.push({ line: i + 1, input: r.input });
    else out.errors.push({ line: i + 1, text: line.slice(0, 60), message: r.error });
  });
  return out;
}
