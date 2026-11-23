// /signals ফর্মের ইনপুট পার্সিং ও যাচাই (বিশুদ্ধ ফাংশন, নেটওয়ার্ক ছাড়া)।
// ফোনে টাইপ করা সহজ করতে: বাংলা অঙ্ক, "1,200", "12K", "1.2M", "~500", "25%" সব চলে।
// যাচাইয়ের নিয়ম SQL ফাংশন record_manual_signal-এর সাথে মেলানো (20261122000000_phase11.sql)।
// তারিখের পার্সার আর অঙ্ক-রূপান্তর /ads-এর (adsparse.ts) থেকেই নেওয়া।
import { normDigits, parseDate } from "./adsparse.ts";

// slug-গুলো SQL-এর check constraint-এর সাথে মেলে। Meta Ads Library এখানে নেই, ওটা /ads দিয়ে যায়।
export const SIGNAL_SOURCES = [
  { slug: "tiktok_creative_center", label: "TikTok Creative Center" },
  { slug: "pinterest_trends", label: "Pinterest Trends" },
  { slug: "infoneen", label: "Infoneen" },
  { slug: "similarweb", label: "Similarweb" },
  { slug: "youtube", label: "YouTube" },
  { slug: "other", label: "অন্য" },
] as const;

export type SignalSource = (typeof SIGNAL_SOURCES)[number]["slug"];

export const sourceLabel = (slug: string): string => SIGNAL_SOURCES.find((s) => s.slug === slug)?.label ?? slug;

export type SignalInput = {
  source: SignalSource;
  keyword: string;
  value: number | null;
  unit: string | null;
  link: string | null;
  note: string | null;
  observed_on: string | null; // YYYY-MM-DD; null = আজ (SQL ফাংশন বাংলাদেশের আজ বসায়)
};

export type SignalParsed = { ok: true; input: SignalInput } | { ok: false; error: string };

const MAX_ABS = 1e12;

// ফাঁকা বা "-" হলে null। "12K" = ১২০০০, "1.2M" = ১২০০০০০, "25%" = ২৫, "-3.5" চলে (কমে-যাওয়া বোঝাতে)।
export function parseValue(raw: string): number | null {
  const s = normDigits(raw).trim().replace(/^[~≈]/, "").replace(/%$/, "").replace(/[,\s]/g, "");
  if (s === "" || s === "-" || s === "–") return null;
  const m = s.match(/^(-?\d+(?:\.\d+)?)([kKmM])?$/);
  if (!m) throw new Error(`মান একটা সংখ্যা হতে হবে (12, 1,200, 12K, 1.2M বা 25% চলে): "${raw.trim()}"`);
  const mult = m[2] ? (m[2].toLowerCase() === "k" ? 1e3 : 1e6) : 1;
  const n = Math.round(Number(m[1]) * mult * 10000) / 10000;
  if (!Number.isFinite(n) || Math.abs(n) >= MAX_ABS) throw new Error(`মান অস্বাভাবিক বড়: "${raw.trim()}"`);
  return n;
}

// ফাঁকা হলে null। শুধু http/https, ফাঁকা ছাড়া, সর্বোচ্চ ৫০০ অক্ষর (javascript: ইত্যাদি আটকাতে)।
export function parseLink(raw: string): string | null {
  const s = raw.trim();
  if (s === "") return null;
  if (!/^https?:\/\/[^\s]+$/i.test(s) || s.length > 500) {
    throw new Error("লিংক http:// বা https:// দিয়ে শুরু হতে হবে, ফাঁকা ছাড়া, সর্বোচ্চ ৫০০ অক্ষর");
  }
  try {
    new URL(s);
  } catch {
    throw new Error(`লিংক ঠিক নয়: "${s.slice(0, 60)}"`);
  }
  return s;
}

export function buildSignal(
  f: { source: string; keyword: string; value?: string; unit?: string; link?: string; note?: string; observed?: string },
  today: string,
): SignalParsed {
  try {
    const source = SIGNAL_SOURCES.find((s) => s.slug === f.source)?.slug;
    if (!source) return { ok: false, error: "সোর্স বেছে নিন" };
    const keyword = f.keyword.trim().replace(/\s+/g, " ");
    if (keyword.length < 1 || keyword.length > 80) return { ok: false, error: "শব্দ ১–৮০ অক্ষরের হতে হবে" };
    const value = parseValue(f.value ?? "");
    const note = (f.note ?? "").trim().slice(0, 200) || null;
    if (value === null && note === null) return { ok: false, error: "মান বা নোট, অন্তত একটা দিন" };
    const unit = (f.unit ?? "").trim().replace(/\s+/g, " ");
    if (unit.length > 24) return { ok: false, error: "একক ২৪ অক্ষরের বেশি হতে পারে না (যেমন ভিউ, সার্চ/মাস, ভিজিট)" };
    const link = parseLink(f.link ?? "");
    const observed_on = parseDate(f.observed ?? "", today);
    return { ok: true, input: { source, keyword, value, unit: unit || null, link, note, observed_on } };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
}
