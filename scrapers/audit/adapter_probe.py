"""Cartup, Othoba ও Bagdoom-এর adapter লেখার আগে আসল লিস্টিং/প্রোডাক্ট পেজের নমুনা তোলা (Phase 10)।

কেন: প্রথম অডিটের নমুনা শুধু হোমপেজ, আর বড় পেজ ৩০০ KB-তে কাটা (Cartup-এর পণ্যের ডেটা কাটা অংশে পড়ে গেছে)। adapter অনুমানে
লেখা হবে না, তাই এখানে প্রতি সাইটে ক্যাটাগরি-লিস্টিং (পেজ ১ ও ২), একটা প্রোডাক্ট পেজ থেকে শুধু কাজের টুকরো সেভ হয়:
কার্ডের HTML, পেজিনেশন লিংক, JSON-LD, Cartup-এর `self.__next_f` ডেটা-চাঙ্ক। মোট ~৩০টা অনুরোধ, robots.txt মেনে,
৩ সেকেন্ড পরপর, টানা ৩ ব্লকে থামে। Cloudflare/ক্যাপচা পাশ কাটানোর চেষ্টা নেই।

ব্যবহার: python -m scrapers.audit.adapter_probe     (ফল: run-output/adapter-probe.md, .json ও adapter-probe/ ফোল্ডার)
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from scrapers.bagdoom import parse as bagdoom
from scrapers.common.http import BlockedError, CircuitOpen, FetchError, PoliteClient, RobotsDisallowed
from scrapers.othoba import parse as othoba

OUT = Path(os.environ.get("RUN_OUT", Path(__file__).resolve().parents[2] / "run-output"))
SNIP = 3500          # একটা টুকরোর সর্বোচ্চ আকার (অক্ষর)

# হোমপেজের নমুনায় পাওয়া আসল ক্যাটাগরি-লিংক (অডিট ২০২৬-১১-২৩)
OTHOBA_CATS = ["/kitchen-dining-4", "/home-decor-7", "/beauty-personal-care-4"]
BAGDOOM_CATS = ["/category/home-lifestyle", "/category/groceries", "/category/womens-and-girls-fashion"]


# ----------------------------------------------------------------- বিশুদ্ধ সহায়ক (অফলাইনে টেস্টযোগ্য)
def extract_jsonld(html: str) -> list:
    out = []
    for b in re.findall(r'<script[^>]*type=["\']?application/ld\+json["\']?[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            out.append(json.loads(b))
        except ValueError:
            out.append({"_unparsed": b[:SNIP]})
    return out


def next_chunks(html: str, needle: str, limit: int = 4) -> list[str]:
    """Next.js `self.__next_f.push([1,"..."])` চাঙ্কের যেগুলোয় needle আছে (escape খুলে, ছোট করে)।"""
    out = []
    for m in re.finditer(r"self\.__next_f\.push\(\[1,(\".*?\")\]\)", html, re.S):
        try:
            txt = json.loads(m.group(1))
        except ValueError:
            continue
        if needle in txt:
            i = txt.find(needle)
            out.append(txt[max(0, i - 600): i + SNIP])
            if len(out) >= limit:
                break
    return out


def pagination_links(html: str, token: str) -> list[str]:
    seen = []
    for m in re.finditer(r'href=(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', html):
        h = (m.group(1) or m.group(2) or m.group(3) or "").replace("&amp;", "&")
        if token in h and h not in seen:
            seen.append(h)
    return seen[:12]


def around(html: str, needle: str, before: int = 700, after: int = 2200, n: int = 2) -> list[str]:
    out, pos = [], 0
    for _ in range(n):
        i = html.find(needle, pos)
        if i < 0:
            break
        out.append(html[max(0, i - before): i + after])
        pos = i + len(needle) + 1
    return out


def sitemap_urls(xml: str) -> list[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)


def title_of(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:160] if m else ""


# ----------------------------------------------------------------- নেটওয়ার্ক ধাপ
class Probe:
    def __init__(self, client: PoliteClient, out: Path):
        self.c, self.out, self.report, self.requests = client, out, {}, 0
        (out / "adapter-probe").mkdir(parents=True, exist_ok=True)

    def save(self, name: str, text: str) -> str:
        p = self.out / "adapter-probe" / name
        p.write_text(text, encoding="utf-8")
        return f"adapter-probe/{name}"

    def fetch(self, url: str):
        self.requests += 1
        try:
            r = self.c.get(url)
            return {"url": url, "final_url": r.url, "status": r.status_code, "bytes": len(r.content), "html": r.text}
        except RobotsDisallowed:
            return {"url": url, "error": "robots.txt নিষেধ করেছে"}
        except BlockedError as e:
            return {"url": url, "error": f"ব্লক ({e})"}
        except CircuitOpen:
            raise
        except FetchError as e:
            return {"url": url, "error": f"ত্রুটি ({e})"}

    def listing(self, site: str, base: str, path: str, page_token: str, cards, snippet_anchor: str):
        rows = []
        for page in (1, 2):
            url = urljoin(base, path) if page == 1 else urljoin(base, path) + (page_token.format(page=page))
            r = self.fetch(url)
            if "html" not in r:
                rows.append(r)
                continue
            h = r.pop("html")
            items = cards(h)
            tag = f"{site}__{path.strip('/').replace('/', '_')}__p{page}"
            r.update(title=title_of(h), parsed_items=len(items), first_items=[{k: it[k] for k in ("external_id", "title", "url", "price", "rating_avg", "review_count")} for it in items[:3]],
                     pagination=pagination_links(h, "page"), snippet=self.save(f"{tag}__cards.html", "\n\n<!-- ---- -->\n\n".join(around(h, snippet_anchor))),
                     first_ids=[it["external_id"] for it in items[:5]])
            rows.append(r)
        if len(rows) == 2 and all("first_ids" in x for x in rows):
            rows[1]["page2_differs_from_page1"] = rows[0]["first_ids"] != rows[1]["first_ids"]
        return rows

    def product_page(self, site: str, url: str, needles: list[str]):
        r = self.fetch(url)
        if "html" not in r:
            return r
        h = r.pop("html")
        r.update(title=title_of(h), jsonld=extract_jsonld(h)[:3],
                 markers={n: h.count(n) for n in needles},
                 data_chunks=next_chunks(h, '"price"', 2) if "__next_f" in h else [],
                 snippets=[self.save(f"{site}__product.html", "\n\n<!-- ---- -->\n\n".join(a for n in needles for a in around(h, n, 500, 1500, 1)))])
        return r


def run(client: PoliteClient, out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    p = Probe(client, out)
    rep: dict = {"othoba": {}, "bagdoom": {}, "cartup": {}}
    try:
        # ---- Othoba (nopCommerce): ?pagenumber=N
        base = "https://www.othoba.com"
        rep["othoba"]["listings"] = {c: p.listing("othoba", base, c, "?pagenumber={page}", othoba.parse_cards, "product-name") for c in OTHOBA_CATS}
        first = next((x["first_items"][0] for rows in rep["othoba"]["listings"].values() for x in rows if x.get("first_items")), None)
        if first:
            rep["othoba"]["product"] = p.product_page("othoba", first["url"], ["new-price", "Reviews", "Brand", "sold", "Sold"])
        # ---- Bagdoom (Active eCommerce): ?page=N
        base = "https://www.bagdoom.com"
        rep["bagdoom"]["listings"] = {c: p.listing("bagdoom", base, c, "?page={page}", bagdoom.parse_cards, "/product/") for c in BAGDOOM_CATS}
        bp = p.fetch(base + "/category/home-lifestyle")
        purl = None
        if "html" in bp:
            m = re.search(r'href="(https://www\.bagdoom\.com/product/[^"]+)"', bp["html"])
            purl = m.group(1) if m else None
        if purl:
            rep["bagdoom"]["product"] = p.product_page("bagdoom", purl, ["৳", "rating", "sold", "Sold", "review", "Brand"])
        # ---- Cartup (Next.js + সাইটম্যাপ)
        cu = "https://cartup.com"
        sm = p.fetch(cu + "/sitemap.xml")
        locs = sitemap_urls(sm.get("html", "")) if "html" in sm else []
        rep["cartup"]["sitemap_index"] = locs
        for kind in ("product", "category"):
            gz = next((u for u in locs if f"sitemap-{kind}-all" in u), None)
            if not gz:
                continue
            p.requests += 1
            try:
                raw = p.c.get_bytes(gz, max_bytes=3_000_000)
                xml = gzip.decompress(raw).decode("utf-8", "replace")
                urls = sitemap_urls(xml)
                rep["cartup"][f"{kind}_sitemap"] = {"url": gz, "urls_in_first_3MB": len(urls), "first": urls[:8], "sample_every_500th": urls[::500][:8]}
            except (RobotsDisallowed, BlockedError, FetchError, OSError) as e:
                rep["cartup"][f"{kind}_sitemap"] = {"url": gz, "error": f"{type(e).__name__}: {e}"}
        prods = (rep["cartup"].get("product_sitemap") or {}).get("sample_every_500th") or []
        rep["cartup"]["products"] = [p.product_page(f"cartup{i}", u, ['"price"', "discountedPrice", "soldCount", "ratingValue", "ratingCount", "brand"]) for i, u in enumerate(prods[:3])]
        cats = (rep["cartup"].get("category_sitemap") or {}).get("first") or []
        if cats:
            r = p.fetch(cats[0])
            if "html" in r:
                h = r.pop("html")
                r.update(title=title_of(h), data_chunks=next_chunks(h, '"price"', 2), jsonld=extract_jsonld(h)[:2],
                         pagination=pagination_links(h, "page"))
            rep["cartup"]["category_page"] = r
    except CircuitOpen as e:
        rep["stopped"] = f"টানা ব্লক, রান থেমেছে: {e}"
    rep["requests"] = p.requests
    (out / "adapter-probe.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = to_markdown(rep)
    (out / "adapter-probe.md").write_text(md, encoding="utf-8")
    return rep


def to_markdown(rep: dict) -> str:
    L = ["# Adapter Probe (Cartup, Othoba, Bagdoom)", "", f"- অনুরোধ: {rep.get('requests', 0)}"]
    if rep.get("stopped"):
        L.append(f"- **{rep['stopped']}**")
    for site in ("othoba", "bagdoom"):
        L += ["", f"## {site}"]
        for cat, rows in (rep[site].get("listings") or {}).items():
            for i, r in enumerate(rows, 1):
                if "error" in r:
                    L.append(f"- `{cat}` পেজ {i}: {r['error']}")
                else:
                    L.append(f"- `{cat}` পেজ {i}: HTTP {r['status']}, {r['bytes']} B, পার্স হলো **{r['parsed_items']}** আইটেম"
                             + (f", পেজ ২ আলাদা: {r['page2_differs_from_page1']}" if "page2_differs_from_page1" in r else "")
                             + (f", পেজিনেশন লিংক: {r['pagination'][:3]}" if r.get("pagination") else ", পেজিনেশন লিংক পাওয়া যায়নি"))
        pr = rep[site].get("product")
        if pr:
            L.append(f"- প্রোডাক্ট পেজ: " + (pr.get("error") or f"HTTP {pr['status']}, JSON-LD {len(pr.get('jsonld', []))}টা, মার্কার {pr.get('markers')}"))
    c = rep["cartup"]
    L += ["", "## cartup"]
    for kind in ("product", "category"):
        s = c.get(f"{kind}_sitemap")
        if s:
            L.append(f"- {kind} সাইটম্যাপ: " + (s.get("error") or f"প্রথম ৩ MB-তে {s['urls_in_first_3MB']}টা URL"))
    for pr in c.get("products", []):
        L.append("- প্রোডাক্ট: " + (pr.get("error") or f"{pr['url']} → HTTP {pr['status']}, JSON-LD {len(pr.get('jsonld', []))}টা, ডেটা-চাঙ্ক {len(pr.get('data_chunks', []))}টা, মার্কার {pr.get('markers')}"))
    cp = c.get("category_page")
    if cp:
        L.append("- ক্যাটাগরি পেজ: " + (cp.get("error") or f"{cp['url']} → HTTP {cp['status']}, ডেটা-চাঙ্ক {len(cp.get('data_chunks', []))}টা"))
    L += ["", "পুরো ফল `adapter-probe.json` ও `adapter-probe/` ফোল্ডারে (কার্ডের HTML টুকরো)।"]
    return "\n".join(L) + "\n"


def main() -> int:
    client = PoliteClient(delay=3.0, jitter=1.0, block_limit=3)
    rep = run(client)
    print(to_markdown(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
