import os
import unittest
from datetime import date, timedelta
from unittest import mock

import requests

from alerts import run_alerts
from alerts.config import load_config
from alerts.notify import NotifyError, build_digest, credentials, send_telegram

CFG = load_config()
TODAY = date(2026, 11, 20)


def d(n):
    return (TODAY - timedelta(days=n)).isoformat()


class FakeResp:
    def __init__(self, code=200, body=None):
        self.status_code, self._body = code, body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp or FakeResp(), exc, []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        if self.exc:
            raise self.exc
        return self.resp


class DigestTests(unittest.TestCase):
    rows = [{"id": 3, "title": "ইনফো", "severity": "info", "watched": False},
            {"id": 1, "title": "ভালো", "severity": "good", "watched": False},
            {"id": 2, "title": "ওয়াচ-সতর্ক", "severity": "warn", "watched": True},
            {"id": 4, "title": "সাধারণ সতর্ক", "severity": "warn", "watched": False}]

    def test_order_watched_first_then_severity(self):
        lines = build_digest(self.rows, "https://dash.example/", 10).splitlines()
        self.assertEqual(lines[0], "🔔 নতুন অ্যালার্ট: 4টা")
        order = ["ওয়াচ-সতর্ক", "সাধারণ সতর্ক", "ভালো", "ইনফো"]
        for line, want in zip(lines[1:5], order):
            self.assertTrue(line.endswith(want), (line, want))
        self.assertTrue(lines[1].startswith("⭐ 🔴"))
        self.assertEqual(lines[-1], "https://dash.example/alerts")

    def test_max_items_and_remainder_and_no_link(self):
        t = build_digest(self.rows, None, 2)
        self.assertIn("…আরও 2টা ড্যাশবোর্ডে", t)
        self.assertNotIn("/alerts", t)

    def test_length_capped(self):
        rows = [{"id": i, "title": "ক" * 500, "severity": "warn", "watched": True} for i in range(30)]
        t = build_digest(rows, None, 30)
        self.assertLessEqual(len(t), 3900)
        self.assertTrue(t.endswith("…"))


class SendTests(unittest.TestCase):
    def test_success_posts_to_bot_endpoint(self):
        s = FakeSession()
        send_telegram("hi", "TOK", "42", s)
        url, body = s.calls[0]
        self.assertEqual(url, "https://api.telegram.org/botTOK/sendMessage")
        self.assertEqual((body["chat_id"], body["text"]), ("42", "hi"))

    def test_http_error_message_has_status_and_description_only(self):
        s = FakeSession(FakeResp(400, {"description": "Bad Request: chat not found"}))
        with self.assertRaises(NotifyError) as c:
            send_telegram("hi", "SECRET-TOKEN", "42", s)
        self.assertIn("400", str(c.exception))
        self.assertIn("chat not found", str(c.exception))
        self.assertNotIn("SECRET-TOKEN", str(c.exception))

    def test_non_json_error_body(self):
        with self.assertRaises(NotifyError) as c:
            send_telegram("hi", "T", "1", FakeSession(FakeResp(502, None)))
        self.assertEqual(str(c.exception), "Telegram HTTP 502")

    def test_network_error_never_leaks_token(self):
        exc = requests.ConnectionError("HTTPSConnectionPool: /botSECRET-TOKEN/sendMessage failed")
        with self.assertRaises(NotifyError) as c:
            send_telegram("hi", "SECRET-TOKEN", "1", FakeSession(exc=exc))
        self.assertNotIn("SECRET-TOKEN", str(c.exception))
        self.assertIsNone(c.exception.__cause__)

    def test_credentials_need_both(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": ""}):
            self.assertIsNone(credentials())
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": " t ", "TELEGRAM_CHAT_ID": "9"}):
            self.assertEqual(credentials(), ("t", "9"))


def match(val, cond):
    op, _, arg = cond.partition(".")
    if op == "gte":
        return val is not None and str(val)[:10] >= arg
    if op == "eq":
        return str(val).lower() == arg
    if op == "is":
        return val is None
    if op == "not":
        return val is not None
    if op == "in":
        return str(val) in arg.strip("()").split(",")
    raise AssertionError(f"fake DB: অজানা ফিল্টার {cond}")


class FakeDB:
    """PostgREST-এর যতটুকু alerts লাগে: eq/gte/is.null/not.is.null/in, order এড়িয়ে (ফিক্সচার আগে থেকেই সাজানো)।"""

    def __init__(self, scores, watch=(), names=None, overview=(), alerts=()):
        self.t = {"product_scores": scores, "watchlist": [{"canonical_product_id": p} for p in watch],
                  "canonical_products": [{"id": k, "name": v} for k, v in (names or {}).items()],
                  "listing_overview": list(overview), "alerts": [dict(a) for a in alerts]}
        self.rpcs, self.next_id = [], 100

    def select(self, table, params=None, page_size=1000):
        params = params or {}
        rows = self.t[table]
        for k, v in params.items():
            if k in ("select", "order", "limit", "offset"):
                continue
            col = {"canonical_product_id": "canonical_product_id"}.get(k, k)
            rows = [r for r in rows if match(r.get(col), v)]
        return [dict(r) for r in rows]

    def upsert(self, table, rows, on_conflict, returning=False, chunk=200):
        keys = on_conflict.split(",")
        for r in rows:
            hit = next((x for x in self.t[table] if all(x.get(k) == r.get(k) for k in keys)), None)
            if hit:
                hit.update(r)            # merge-duplicates: কেবল পাঠানো কলাম বদলায়
            else:
                self.next_id += 1
                self.t[table].append({"id": self.next_id, "seen_at": None, "notified_at": None, **r})
        return []

    def rpc(self, fn, args=None):
        self.rpcs.append((fn, args))
        if fn == "mark_alerts_notified":
            for a in self.t["alerts"]:
                if a["id"] in args["p_ids"] and a["notified_at"] is None:
                    a["notified_at"] = "now"
        return 0 if fn == "prune_alerts" else None


def score_row(pid, days_ago, tier, total, cf=None):
    return {"canonical_product_id": pid, "scored_on": d(days_ago), "tier": tier, "total": total,
            "confidence": "high", "cf_n": cf}


def basic_db(**kw):
    scores = [score_row(1, 0, "best", 80, "3"), score_row(1, 1, "mid", 79), score_row(1, 7, "mid", 50),
              score_row(2, 0, "best", 77), score_row(2, 1, "mid", 76),
              score_row(3, 0, "mid", 50), score_row(3, 1, "mid", 50)]
    return FakeDB(scores, watch=[1], names={1: "A", 2: "B", 3: "C"},
                  overview=[{"canonical_product_id": 1, "price": 80, "price_delta_7d": -20, "is_active": True}], **kw)


class RunTests(unittest.TestCase):
    def test_creates_expected_alerts(self):
        db = basic_db()
        out = run_alerts.run(db, CFG, TODAY, no_notify=True)
        got = sorted((a["canonical_product_id"], a["kind"], a["watched"]) for a in out["alerts"])
        self.assertEqual(got, [(1, "price_move", True), (1, "redflag", True), (1, "score_move", True),
                               (1, "tier_change", True), (2, "tier_change", False)])
        self.assertEqual(len(db.t["alerts"]), 5)
        self.assertEqual(out["info"], {"scored_today": 3, "watch": 1})
        self.assertTrue(any(a["title"].startswith("A: Mid → Best") for a in db.t["alerts"]))
        self.assertIn(("prune_alerts", {"p_keep_days": 60}), db.rpcs)

    def test_rerun_same_day_creates_no_duplicates_and_keeps_seen(self):
        db = basic_db()
        run_alerts.run(db, CFG, TODAY, no_notify=True)
        db.t["alerts"][0]["seen_at"] = "yesterday"
        run_alerts.run(db, CFG, TODAY, no_notify=True)
        self.assertEqual(len(db.t["alerts"]), 5)
        self.assertEqual(db.t["alerts"][0]["seen_at"], "yesterday")

    def test_dry_run_writes_nothing(self):
        db = basic_db()
        out = run_alerts.run(db, CFG, TODAY, dry=True)
        self.assertEqual(len(out["alerts"]), 5)
        self.assertEqual(db.t["alerts"], [])
        self.assertEqual(db.rpcs, [])
        self.assertIn("dry-run", out["markdown"])

    def test_no_scores_today_means_no_alerts_and_no_crash(self):
        db = FakeDB([score_row(1, 1, "mid", 50)], watch=[1])
        out = run_alerts.run(db, CFG, TODAY, no_notify=True)
        self.assertEqual((out["alerts"], out["info"]["scored_today"]), ([], 0))

    def test_watch_outside_todays_scores_is_ignored(self):
        db = FakeDB([score_row(1, 0, "mid", 50), score_row(1, 1, "mid", 50)], watch=[1, 999])
        self.assertEqual(run_alerts.run(db, CFG, TODAY, no_notify=True)["info"]["watch"], 1)

    def test_old_history_is_ignored_for_tier_change(self):
        # শুধু ১২ দিন আগের স্কোর: "আগের দিন" নেই, তাই ট্যাগ-বদল ধরা হয় না (ফাঁক পেরিয়ে তুলনা নয়)
        db = FakeDB([score_row(2, 0, "best", 80)], watch=[])
        self.assertEqual(run_alerts.run(db, CFG, TODAY, no_notify=True)["alerts"], [])


class NotifyRunTests(unittest.TestCase):
    ENV = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "7", "DASHBOARD_URL": "https://d.example"}

    def test_sends_once_then_marks_notified(self):
        db = basic_db()
        sent = []
        with mock.patch.dict(os.environ, self.ENV), \
                mock.patch.object(run_alerts, "send_telegram", lambda text, tok, chat: sent.append((text, tok, chat))):
            out = run_alerts.run(db, CFG, TODAY)
            self.assertEqual(len(sent), 1)
            self.assertIn("5টা পাঠানো হয়েছে", out["notify"])
            self.assertEqual(sent[0][1:], ("tok", "7"))
            self.assertIn("https://d.example/alerts", sent[0][0])
            self.assertTrue(all(a["notified_at"] for a in db.t["alerts"]))
            run_alerts.run(db, CFG, TODAY)               # আবার চালালে নতুন কিছু নেই
            self.assertEqual(len(sent), 1)

    def test_failed_send_keeps_alerts_pending_and_run_succeeds(self):
        db = basic_db()

        def boom(*a):
            raise NotifyError("Telegram HTTP 500")
        with mock.patch.dict(os.environ, self.ENV), mock.patch.object(run_alerts, "send_telegram", boom):
            out = run_alerts.run(db, CFG, TODAY)
        self.assertIn("ব্যর্থ", out["notify"])
        self.assertTrue(all(a["notified_at"] is None for a in db.t["alerts"]))
        self.assertEqual(len(db.t["alerts"]), 5)

    def test_no_credentials_or_disabled(self):
        env = {k: "" for k in self.ENV}
        with mock.patch.dict(os.environ, env):
            self.assertIn("দেওয়া নেই", run_alerts.run(basic_db(), CFG, TODAY)["notify"])
        off = {**CFG, "telegram": {**CFG["telegram"], "enabled": False}}
        with mock.patch.dict(os.environ, self.ENV):
            self.assertIn("বন্ধ", run_alerts.run(basic_db(), off, TODAY)["notify"])

    def test_dry_run_does_not_send(self):
        sent = []
        with mock.patch.dict(os.environ, self.ENV), mock.patch.object(run_alerts, "send_telegram", lambda *a: sent.append(a)):
            out = run_alerts.run(basic_db(), CFG, TODAY, dry=True)
        self.assertEqual(sent, [])
        self.assertIn("dry-run", out["notify"])


if __name__ == "__main__":
    unittest.main()
