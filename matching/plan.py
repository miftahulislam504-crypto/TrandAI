"""ম্যাচিং পরিকল্পনা: কোন জোড়া নিজে মার্জ হবে, কোনটা রিভিউ কিউতে যাবে।

সুরক্ষা (ভুল মার্জ সবচেয়ে ব্যয়বহুল, কারণ দুই প্রোডাক্টের বিক্রি যোগ হয়ে যায়):
- চেইন-মার্জ আটকানো: A~B আর B~C নিজে মিললেও A আর C-তে সংঘাত থাকলে সব তিনটা একসাথে মার্জ হয় না, নতুন জোড়াটা রিভিউতে যায়
- গ্রুপের আকার max_cluster_size-এর বেশি হতে পারে না
- আগে reject করা জোড়ার দুই পাশের প্রোডাক্ট আর কখনও নিজে মার্জ হয় না
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .parse import brand_conflict, unit_conflict
from .score import Item, Pair, candidate_pairs, decide, idf_weights, prepare, score_pair


@dataclass
class Plan:
    auto: list[Pair] = field(default_factory=list)
    review: list[Pair] = field(default_factory=list)
    merges: list[tuple[int, int]] = field(default_factory=list)     # (winner canonical, loser canonical)
    stats: dict = field(default_factory=dict)


def _canon(it: Item) -> Optional[int]:
    return it.canonical_id


def build_plan(items: list[Item], cfg: dict, decided: Optional[dict[tuple[int, int], str]] = None) -> Plan:
    """decided: {(listing_a, listing_b): 'accepted'|'rejected'|'auto'}, আগের সিদ্ধান্ত।"""
    decided = decided or {}
    items = [it for it in items if it.canonical_id is not None]
    prep = prepare(items, cfg)
    byid = {it.id: it for it in items}
    idf = idf_weights(items)

    # reject করা জোড়া -> canonical জোড়া ব্লক
    blocked: set[frozenset[int]] = set()
    for (la, lb), st in decided.items():
        if st == "rejected" and la in byid and lb in byid:
            ca, cb = _canon(byid[la]), _canon(byid[lb])
            if ca != cb:
                blocked.add(frozenset((ca, cb)))

    plan = Plan()
    st = {"image_ambiguous": prep["image_ambiguous"], "image_lifted": 0, "candidates": 0, "conflicts": 0, "same_canonical": 0, "already_decided": 0, "blocked": 0, "below_review": 0}
    pairs: list[Pair] = []
    for x, y in candidate_pairs(items, idf, cfg):
        st["candidates"] += 1
        p = score_pair(x, y, idf, cfg)
        if _canon(x) == _canon(y):
            st["same_canonical"] += 1
            continue
        if (p.a, p.b) in decided:
            st["already_decided"] += 1
            continue
        if p.conflict:
            st["conflicts"] += 1
            continue
        if frozenset((_canon(x), _canon(y))) in blocked:
            st["blocked"] += 1
            continue
        p.decision = decide(p, cfg)
        if p.decision is None:
            st["below_review"] += 1
            continue
        if p.image_lift:
            st["image_lifted"] += 1
        pairs.append(p)

    # গ্রুপ: canonical -> সদস্য listing-এর তালিকা
    group_of: dict[int, set[int]] = {}
    members: dict[int, list[Item]] = {}
    for it in items:
        members.setdefault(_canon(it), []).append(it)
    for c in members:
        group_of[c] = {c}                       # গ্রুপ = canonical আইডির সেট
    gid: dict[int, int] = {c: c for c in members}   # canonical -> গ্রুপ-নেতা

    def group_items(leader: int) -> list[Item]:
        return [it for c in group_of[leader] for it in members[c]]

    for p in sorted((p for p in pairs if p.decision == "auto"), key=lambda p: -p.score):
        ca, cb = gid[_canon(byid[p.a])], gid[_canon(byid[p.b])]
        if ca == cb:
            plan.auto.append(p)
            continue
        ga, gb = group_items(ca), group_items(cb)
        reason = None
        if len(ga) + len(gb) > cfg["max_cluster_size"]:
            reason = "cluster_too_big"
        elif any(frozenset((_canon(x), _canon(y))) in blocked for x in ga for y in gb):
            reason = "blocked_pair"
        elif any(brand_conflict(x.parsed, y.parsed) or unit_conflict(x.parsed, y.parsed, cfg["unit_tolerance"])
                 for x in ga for y in gb):
            reason = "cluster_conflict"
        if reason:
            p.decision, p.note = "review", reason
            continue
        for c in group_of[cb]:
            gid[c] = ca
        group_of[ca] |= group_of[cb]
        del group_of[cb]
        plan.auto.append(p)

    # মার্জ তালিকা: প্রতি গ্রুপে সর্বনিম্ন id জেতে (পুরনো, স্কোরের ইতিহাস থাকে)
    for leader, cs in group_of.items():
        if len(cs) > 1:
            winner = min(cs)
            plan.merges += [(winner, c) for c in sorted(cs) if c != winner]

    # এই রানেই অন্য সুতোয় একই গ্রুপে চলে যাওয়া জোড়া রিভিউতে পাঠানোর দরকার নেই
    review = [p for p in pairs if p.decision == "review"
              and gid[_canon(byid[p.a])] != gid[_canon(byid[p.b])]]
    review.sort(key=lambda p: -p.score)
    st["review_total"] = len(review)
    plan.review = review[: cfg["max_review_per_run"]]
    st["review_dropped_by_cap"] = len(review) - len(plan.review)
    plan.stats = st
    return plan
