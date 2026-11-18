// CSV বানানো। Excel/Google Sheets-এ বাংলা ঠিকমতো খুলতে শুরুতে UTF-8 BOM, লাইন শেষ CRLF।
// সুরক্ষা: যে লেখা = + - @ বা ট্যাব/CR দিয়ে শুরু হয় (Daraz-এর টাইটেল বা সেলারের নাম হতে পারে), Excel সেটাকে সূত্র
// ধরে চালায় (CSV injection)। তাই এমন লেখার আগে ' বসে। সংখ্যা (number) আসল সংখ্যাই থাকে, ঋণাত্মক হলেও।
export type Cell = string | number | boolean | null | undefined;

export function cell(v: Cell): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
  if (typeof v === "boolean") return v ? "true" : "false";
  let s = String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(headers: string[], rows: Cell[][]): string {
  const lines = [headers, ...rows].map((r) => r.map(cell).join(","));
  return "\uFEFF" + lines.join("\r\n") + "\r\n";
}
