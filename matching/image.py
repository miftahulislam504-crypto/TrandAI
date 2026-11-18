"""ছবির মিল: 64-বিট dHash, দূরত্ব (Hamming), বিভ্রান্তিকর হ্যাশ ছাঁটা, ছবি দিয়ে জোড়া খোঁজা।

dHash মানে ছবিকে ৯×৮ ধূসরে ছোট করে প্রতি সারিতে পাশের পিক্সেলের চেয়ে উজ্জ্বল কি না (৬৪ বিট)। একই ছবি
ছোট-বড় বা কম্প্রেস করা হলেও হ্যাশ প্রায় একই থাকে (দূরত্ব ০-৬), আলাদা ছবির দূরত্ব সাধারণত ২০-এর উপরে।

কী পারে: একই ছবি কপি করা সেলার ও সাইট ধরা (\"No Brand\" প্রোডাক্টে সবচেয়ে কাজের)।
কী পারে না: একই প্রোডাক্টের আলাদা ছবি (ভিন্ন কোণ বা ভিন্ন ফটো) ধরা। তাই ছবি শুধু প্রমাণ বাড়ায়, ছবি আলাদা
মানে আলাদা প্রোডাক্ট নয়। ছবির বেলায় নিজে মার্জও হয় না, শুধু রিভিউ কিউতে যায় (score.py-তে সীমা আছে)।
"""
from __future__ import annotations

import io
from collections import Counter, defaultdict
from itertools import combinations
from typing import Iterable, Optional

HASH_BITS = 64


class ImageError(ValueError):
    pass


def dhash_bytes(data: bytes, min_bits: int = 10) -> Optional[int]:
    """ছবির bytes -> 64-বিট পূর্ণসংখ্যা। ছবিটা খুব সমতল (প্রায় সব বিট ০ বা ১) হলে None, কারণ সেই হ্যাশ ভরসাযোগ্য নয়।
    পড়া না গেলে ImageError।"""
    try:
        from PIL import Image  # দেরিতে আমদানি: Pillow না থাকলে শুধু হ্যাশ করা অচল, বাকি ম্যাচিং চলে
    except ImportError as e:  # pragma: no cover
        raise ImageError("Pillow ইনস্টল নেই (pip install Pillow)") from e
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.draft("L", (64, 64))          # JPEG হলে ডিকোডেই ছোট করে, দ্রুত ও কম মেমরি
            if im.width * im.height > 50_000_000:
                raise ImageError("ছবি অস্বাভাবিক বড়")
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGBA", im.size, (255, 255, 255, 255))   # স্বচ্ছ অংশ সাদা ধরা
                im = Image.alpha_composite(bg, im)
            g = im.convert("L").resize((HASH_BITS // 8 + 1, 8), Image.Resampling.LANCZOS)
            px = list(g.get_flattened_data() if hasattr(g, "get_flattened_data") else g.getdata())
    except ImageError:
        raise
    except Exception as e:                    # ভাঙা/অচেনা ফাইল
        raise ImageError(f"ছবি পড়া যায়নি: {type(e).__name__}") from e
    w, h = HASH_BITS // 8 + 1, 8
    bits = 0
    for y in range(h):
        for x in range(w - 1):
            bits = (bits << 1) | (1 if px[y * w + x] > px[y * w + x + 1] else 0)
    ones = bits.bit_count()
    if ones < min_bits or ones > HASH_BITS - min_bits:
        return None
    return bits


def to_hex(h: int) -> str:
    return f"{h:016x}"


def from_hex(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(s, 16) if len(s) == 16 else None
    except ValueError:
        return None


def distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def drop_ambiguous(hashes: dict[int, int], max_group: int) -> tuple[dict[int, int], int]:
    """{listing id: hash}। একই (বা প্রায় একই) ছবি max_group-এর বেশি listing-এ থাকলে সেটা সাইটের ডিফল্ট/\"ছবি নেই\"
    প্লেসহোল্ডার বা ব্যানার ধরে সব বাদ। (একই প্রোডাক্ট ১০-১২ সেলারে থাকতে পারে, শত শত নয়।)
    ফেরত: (টিকে থাকা, বাদ পড়ার সংখ্যা)।"""
    cnt = Counter(hashes.values())
    bad = {h for h, c in cnt.items() if c > max_group}
    kept = {i: h for i, h in hashes.items() if h not in bad}
    return kept, len(hashes) - len(kept)


def near_pairs(hashes: dict[int, int], max_dist: int, posting_cap: int = 200) -> list[tuple[int, int, int]]:
    """{id: hash} থেকে দূরত্ব <= max_dist সব জোড়া: [(id_a, id_b, দূরত্ব)], id_a < id_b।
    বহু-সূচক (multi-index) কৌশল: ৬৪ বিটকে max_dist+1 টুকরো করলে দূরত্ব <= max_dist জোড়ার অন্তত একটা টুকরো হুবহু মেলে
    (কবুতরের খুপরি নীতি), তাই শুধু একই টুকরোর খুপরির ভেতর যাচাই করলেই সব জোড়া ধরা পড়ে, সবার সাথে সবাইকে নয়।
    posting_cap-এর বড় খুপরি (যেমন সব-শূন্য টুকরো) বাদ, নইলে জোড়া বিস্ফোরিত হয়; অন্য টুকরোতে তবু ধরা পড়ে।"""
    if len(hashes) < 2:
        return []
    k = min(HASH_BITS, max(1, max_dist + 1))
    edges = [round(i * HASH_BITS / k) for i in range(k + 1)]
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int, int]] = []
    for ci in range(k):
        lo, hi = edges[ci], edges[ci + 1]
        mask = (1 << (hi - lo)) - 1
        buckets: dict[int, list[int]] = defaultdict(list)
        for i, h in hashes.items():
            buckets[(h >> lo) & mask].append(i)
        for ids in buckets.values():
            if len(ids) < 2 or len(ids) > posting_cap:
                continue
            for x, y in combinations(ids, 2):
                key = (x, y) if x < y else (y, x)
                if key in seen:
                    continue
                seen.add(key)
                d = distance(hashes[x], hashes[y])
                if d <= max_dist:
                    out.append((key[0], key[1], d))
    return out


def group_by_category(items: Iterable) -> dict[str, list]:
    g: dict[str, list] = defaultdict(list)
    for it in items:
        if it.category and it.image_hash is not None:
            g[it.category].append(it)
    return g
