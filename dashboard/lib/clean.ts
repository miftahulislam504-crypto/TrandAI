// ডাটাবেজে আগের রানের লেখায় (স্কোরের কারণ, অ্যালার্টের শিরোনাম, নোট) ইমোজি থেকে যেতে পারে।
// দেখানোর আগে এখান দিয়ে ছেঁকে ফেলা হয়। ডাটাবেজের লেখা বদলায় না।
// বাংলা র-ফলা (র + ZWJ + ্য) ভাঙে না, তাই ZWJ শুধু ইমোজির জোড়ার ভেতরেই সরে।
const SEQ = /[0-9#*]\uFE0F?\u20E3|(?:\p{Regional_Indicator}{2}|\p{Extended_Pictographic}\p{Emoji_Modifier}?)(?:\uFE0F|\u200D\p{Extended_Pictographic}\p{Emoji_Modifier}?)*/gu;
// ফোনে ইমোজি হয়ে দেখায় এমন চিহ্ন, আর ভেসে-থাকা ভ্যারিয়েশন সিলেক্টর
const SYMBOLS = /[\u2605\u2606\u2713\u2714\u2717\u2718\u2715\u2716\u26AA\u26AB\u25B2\u25BC\uFE0F]/g;

export function stripEmoji(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(SEQ, "").replace(SYMBOLS, "").replace(/[ \t]{2,}/g, " ").replace(/^[ \t]+|[ \t]+$/gm, "").trim();
}
