export const num = (n: number | null | undefined) =>
  n === null || n === undefined ? "–" : Number(n).toLocaleString("en-US");

export const taka = (n: number | null | undefined) =>
  n === null || n === undefined ? "–" : "৳" + Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

export const delta = (n: number | null | undefined) =>
  n === null || n === undefined ? "–" : (n > 0 ? "+" : "") + Number(n).toLocaleString("en-US");

export const rating = (n: number | null | undefined) =>
  n === null || n === undefined ? "–" : Number(n).toFixed(1);

export const day = (s: string | null | undefined) => (s ? s.slice(0, 10) : "–");
