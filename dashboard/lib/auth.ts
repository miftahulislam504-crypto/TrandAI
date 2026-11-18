// Basic Auth যাচাই। middleware ও প্রতিটা পেজ দুই জায়গাতেই ব্যবহার হয় (দ্বিস্তর সুরক্ষা)।
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export function isAuthorized(header: string | null): boolean {
  const pass = process.env.DASHBOARD_PASSWORD;
  if (!pass || !header || !header.startsWith("Basic ")) return false;
  let decoded = "";
  try {
    const bytes = Uint8Array.from(atob(header.slice(6)), (c) => c.charCodeAt(0));
    decoded = new TextDecoder().decode(bytes);
  } catch {
    return false;
  }
  const i = decoded.indexOf(":");
  if (i < 0) return false;
  const user = process.env.DASHBOARD_USER || "admin";
  const userOk = safeEqual(decoded.slice(0, i), user);
  const passOk = safeEqual(decoded.slice(i + 1), pass);
  return userOk && passOk;
}
