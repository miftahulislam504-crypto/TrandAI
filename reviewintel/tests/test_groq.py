"""Groq key-পুল ও সেন্টিমেন্ট রানারের টেস্ট। আসল Groq নয়, নকল HTTP দিয়ে (আমার এনভায়রনমেন্ট থেকে api.groq.com-এ যাওয়া যায় না)।"""
import json
import unittest

from reviewintel import run_sentiment as rs
from reviewintel.config import IntelConfigError, load_config
from reviewintel.groq_pool import (AllKeysExhausted, BadRequest, GroqPool, ModelUnavailable, NoKeys, RequestTooLarge,
                                   keys_from_env)

CFG = load_config()


class Resp:
    def __init__(self, status=200, body=None, headers=None, text=""):
        self.status_code, self._body, self.headers, self.text = status, body, headers or {}, text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def ok(results, tokens=100):
    return Resp(200, {"choices": [{"message": {"content": json.dumps({"results": results})}}], "usage": {"total_tokens": tokens}})


def err(status, message, retry_after=None, code=""):
    h = {"retry-after": str(retry_after)} if retry_after is not None else {}
    return Resp(status, {"error": {"message": message, "code": code}}, h)


class Net:
    """key অনুযায়ী সাজানো উত্তরের তালিকা। শেষ উত্তর বারবার চলে। ঘুম ও সময় নকল।"""
    def __init__(self, script):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls = []
        self.t = 1000.0
        self.slept = []

    def post(self, url, headers, payload, timeout):
        key = headers["Authorization"].split()[-1]
        self.calls.append((key, payload["model"]))
        q = self.script[key]
        r = q.pop(0) if len(q) > 1 else q[0]
        if isinstance(r, Exception):
            raise r
        return r

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def pool(script, keys=("k1", "k2", "k3"), **kw):
    n = Net(script)
    return GroqPool([(f"GROQ{i + 1}", k) for i, k in enumerate(keys)], post=n.post, now=n.now, sleep=n.sleep, **kw), n


PAYLOAD = {"model": "m", "messages": []}


class KeyEnvTests(unittest.TestCase):
    def test_names_and_order(self):
        env = {"GROQ2": "b", "GROQ1": "a", "GROQ_API_KEY_3": "c", "GROQ10": "j", "GROQ_API_KEY": "z", "OTHER": "x", "GROQ4": " ", "GROQ5": "a"}
        self.assertEqual(keys_from_env(env), [("GROQ1", "a"), ("GROQ2", "b"), ("GROQ_API_KEY_3", "c"), ("GROQ10", "j"), ("GROQ_API_KEY", "z")])

    def test_none(self):
        self.assertEqual(keys_from_env({"PATH": "/bin"}), [])
        with self.assertRaises(NoKeys):
            GroqPool([])


class PoolTests(unittest.TestCase):
    def test_sticks_to_first_key_while_it_works(self):
        p, n = pool({"k1": [ok([])], "k2": [ok([])]})
        for _ in range(3):
            p.call(PAYLOAD)
        self.assertEqual([c[0] for c in n.calls], ["k1"] * 3)
        self.assertEqual(p.usage()[0]["tokens"], 300)

    def test_daily_limit_moves_to_next_key_for_good(self):
        p, n = pool({"k1": [err(429, "Rate limit reached for model on tokens per day (TPD): Limit 200000", retry_after=3000)], "k2": [ok([])]})
        p.call(PAYLOAD)
        p.call(PAYLOAD)
        self.assertEqual([c[0] for c in n.calls], ["k1", "k2", "k2"])
        self.assertEqual(p.usage()[0]["state"], "শেষ")

    def test_minute_limit_cools_then_returns_to_first_key(self):
        p, n = pool({"k1": [err(429, "tokens per minute (TPM)", retry_after=20), ok([])], "k2": [ok([])]})
        p.call(PAYLOAD)                       # k1 ৪২৯ -> k2
        self.assertEqual([c[0] for c in n.calls], ["k1", "k2"])
        n.t += 30                             # k1-র বিশ্রাম শেষ
        p.call(PAYLOAD)
        self.assertEqual(n.calls[-1][0], "k1")
        self.assertEqual(p.usage()[0]["state"], "চলছে")

    def test_all_cooling_sleeps_shortest_then_retries(self):
        p, n = pool({"k1": [err(429, "per minute", retry_after=10), ok([])], "k2": [err(429, "per minute", retry_after=5), ok([])]}, keys=("k1", "k2"))
        p.call(PAYLOAD)
        self.assertTrue(n.slept and 5 <= n.slept[0] <= 7)
        self.assertEqual(n.calls[-1][0], "k2")

    def test_long_wait_counts_as_exhausted(self):
        p, n = pool({"k1": [err(429, "limit", retry_after=900)], "k2": [err(429, "limit", retry_after=900)]}, keys=("k1", "k2"))
        with self.assertRaises(AllKeysExhausted):
            p.call(PAYLOAD)

    def test_all_exhausted(self):
        p, _ = pool({k: [err(429, "requests per day (RPD)")] for k in ("k1", "k2", "k3")})
        with self.assertRaises(AllKeysExhausted):
            p.call(PAYLOAD)
        self.assertTrue(all(u["state"] == "শেষ" for u in p.usage()))

    def test_bad_key_is_dropped(self):
        p, n = pool({"k1": [err(401, "Invalid API Key")], "k2": [ok([])]})
        p.call(PAYLOAD)
        self.assertEqual(p.usage()[0]["state"], "অচল")
        p.call(PAYLOAD)
        self.assertEqual([c[0] for c in n.calls], ["k1", "k2", "k2"])

    def test_server_errors_retry_then_move_on(self):
        p, n = pool({"k1": [Resp(503, {"error": {"message": "x"}})], "k2": [ok([])]})
        p.call(PAYLOAD)
        self.assertEqual([c[0] for c in n.calls], ["k1", "k1", "k1", "k2"])    # ১ + ২ পুনঃচেষ্টা, তারপর পরের key
        self.assertEqual(p.usage()[0]["state"], "চলছে")                        # বিশ্রামে, বাতিল নয়

    def test_network_error_then_success(self):
        p, n = pool({"k1": [ConnectionError("boom"), ok([])]})
        p.call(PAYLOAD)
        self.assertEqual(len(n.calls), 2)

    def test_model_and_size_and_bad_request(self):
        p, _ = pool({"k1": [err(404, "The model `x` has been decommissioned and is no longer supported", code="model_decommissioned")]})
        with self.assertRaises(ModelUnavailable):
            p.call(PAYLOAD)
        p, _ = pool({"k1": [err(413, "Request too large for model on TPM")]})
        with self.assertRaises(RequestTooLarge):
            p.call(PAYLOAD)
        p, _ = pool({"k1": [err(400, "response_format unsupported")]})
        with self.assertRaises(BadRequest):
            p.call(PAYLOAD)

    def test_keys_never_leak_into_events(self):
        p, _ = pool({"sk-SECRET1": [err(429, "invalid key sk-SECRET1 per day")], "sk-SECRET2": [ok([])]}, keys=("sk-SECRET1", "sk-SECRET2"))
        p.call(PAYLOAD)
        text = " ".join(p.events)
        self.assertNotIn("SECRET", text)
        self.assertIn("GROQ1", text)


# ------------------------------------------------------------------ রানার
class DB:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.updates = []

    def select(self, table, params=None, page_size=1000):
        return [dict(r) for r in self.rows if r.get("sentiment") is None and not r.get("suspected_fake") and r.get("body")]

    def update(self, table, values, params):
        ids = [int(x) for x in params["id"][4:-1].split(",")]
        self.updates.append((values, ids))
        for r in self.rows:
            if r["id"] in ids:
                r.update(values)


def rev(i, body="খুব ভালো প্রোডাক্ট", stars=5, **kw):
    return {"id": i, "stars": stars, "body": body, "sentiment": None, "suspected_fake": False, **kw}


def answer(payload):
    """নকল মডেল: লেখায় 'bad' থাকলে -১ (টপিক quality), নইলে +১।"""
    items = json.loads(payload["messages"][1]["content"].split("\n", 1)[1])
    return [{"i": x["i"], "s": -1 if "bad" in x["text"] else 1, "t": ["quality"]} for x in items]


class SmartNet(Net):
    def post(self, url, headers, payload, timeout):
        key = headers["Authorization"].split()[-1]
        self.calls.append((key, payload["model"]))
        q = self.script[key]
        r = q.pop(0) if len(q) > 1 else q[0]
        if r == "ANSWER":
            return ok(answer(payload), tokens=200)
        return r


def runner(rows, script, keys=("k1", "k2"), cfg=CFG, **kw):
    n = SmartNet(script)
    p = GroqPool([(f"GROQ{i + 1}", k) for i, k in enumerate(keys)], post=n.post, now=n.now, sleep=n.sleep)
    db = DB(rows)
    r = rs.Runner(db, p, cfg, clock=n.now, **kw)
    return r, db, n


class ParseTests(unittest.TestCase):
    T = CFG["sentiment"]["topics"]

    def test_valid_and_dirty(self):
        c = '```json\n{"results":[{"i":0,"s":1,"t":["quality","price","nonsense"]},{"i":1,"s":-1,"t":[]}]}\n```'
        self.assertEqual(rs.parse_results(c, 2, self.T), {0: (1, ("price", "quality")), 1: (-1, ())})

    def test_bad_rows_are_dropped_not_fatal(self):
        c = json.dumps({"results": [{"i": 0, "s": 2}, {"i": 5, "s": 1}, {"i": 1, "s": True}, {"i": 1, "s": 0, "t": "quality"}, {"i": 1, "s": 1}, "x", {"i": 2}]})
        self.assertEqual(rs.parse_results(c, 3, self.T), {1: (0, ())})

    def test_garbage_raises(self):
        for bad in ("", "sorry I cannot", '{"results": 5}', "{broken"):
            with self.assertRaises(rs.SentimentError):
                rs.parse_results(bad, 2, self.T)

    def test_prompt_contains_texts_and_topics(self):
        m = rs.build_messages([rev(1, body="x" * 900)], CFG)
        self.assertIn("quality", m[0]["content"])
        self.assertLessEqual(len(json.loads(m[1]["content"].split("\n", 1)[1])[0]["text"]), CFG["sentiment"]["max_chars_per_review"])


class RunnerTests(unittest.TestCase):
    def test_classifies_and_writes_grouped(self):
        rows = [rev(1), rev(2, "this is bad", 1), rev(3), rev(4, "খুব ভালো প্রোডাক্ট", suspected_fake=True), rev(5, "")]
        r, db, _ = runner(rows, {"k1": ["ANSWER"]})
        pending = rs.fetch_pending(db, CFG)
        self.assertEqual({x["id"] for x in pending}, {1, 2, 3})           # ফেক ও ফাঁকা বাদ
        r.run(pending)
        self.assertEqual(r.stop, None)
        got = {x["id"]: (x["sentiment"], x.get("topics")) for x in db.rows}
        self.assertEqual(got[2], (-1, ["quality"]))
        self.assertEqual(got[1], (1, ["quality"]))
        self.assertEqual(got[4], (None, None))
        self.assertEqual(len(db.updates), 2)                              # (+১,quality) ও (-১,quality) দুই গ্রুপ

    def test_batches_respect_size(self):
        r, db, n = runner([rev(i) for i in range(1, 31)], {"k1": ["ANSWER"]})
        r.run(rs.fetch_pending(db, CFG))
        self.assertEqual(len(n.calls), 3)                                 # ১২+১২+৬

    def test_rotates_keys_when_first_hits_daily_limit(self):
        r, db, n = runner([rev(i) for i in range(1, 31)], {"k1": ["ANSWER", err(429, "tokens per day (TPD)", retry_after=5000)], "k2": ["ANSWER"]})
        r.run(rs.fetch_pending(db, CFG))
        self.assertEqual(r.stop, None)
        self.assertTrue(all(x["sentiment"] is not None for x in db.rows))
        self.assertEqual([c[0] for c in n.calls], ["k1", "k1", "k2", "k2"])
        s = rs.summarize(r, 30, False)
        self.assertEqual(s["keys"][0]["state"], "শেষ")
        self.assertEqual(s["classified"], 30)

    def test_all_keys_exhausted_keeps_progress(self):
        r, db, _ = runner([rev(i) for i in range(1, 31)], {"k1": ["ANSWER", err(429, "per day")], "k2": [err(429, "per day")]})
        r.run(rs.fetch_pending(db, CFG))
        self.assertEqual(r.stop, "keys_exhausted")
        done = [x for x in db.rows if x["sentiment"] is not None]
        self.assertEqual(len(done), 12)                                   # প্রথম ব্যাচ রয়ে গেছে, বাকিটা পরের রানে
        self.assertIn("পরের রানে", rs.summary_markdown(rs.summarize(r, 30, False)))

    def test_model_fallback(self):
        r, db, n = runner([rev(1)], {"k1": [err(404, "The model has been decommissioned", code="model_decommissioned"), "ANSWER"]})
        r.run(rs.fetch_pending(db, CFG))
        self.assertEqual([c[1] for c in n.calls], ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])
        self.assertEqual(db.rows[0]["sentiment"], 1)

    def test_all_models_gone(self):
        r, _, _ = runner([rev(1)], {"k1": [err(404, "model not found")]})
        r.run(rs.fetch_pending(DB([rev(1)]), CFG))
        self.assertEqual(r.stop, "no_model")

    def test_reasoning_param_rejected_is_retried_without(self):
        seen = []

        class N(SmartNet):
            def post(self, url, headers, payload, timeout):
                seen.append("reasoning_effort" in payload)
                return err(400, "reasoning_effort is not supported with this model") if len(seen) == 1 else ok(answer(payload))
        n = N({"k1": [None]})
        p = GroqPool([("GROQ1", "k1")], post=n.post, now=n.now, sleep=n.sleep)
        db = DB([rev(1)])
        r = rs.Runner(db, p, CFG, clock=n.now)
        r.run(rs.fetch_pending(db, CFG))
        self.assertEqual(seen, [True, False])
        self.assertEqual(db.rows[0]["sentiment"], 1)

    def test_unparsable_answer_splits_and_gives_up_on_single(self):
        r, db, n = runner([rev(1), rev(2)], {"k1": [Resp(200, {"choices": [{"message": {"content": "no json"}}]})]})
        r.run(rs.fetch_pending(db, CFG))
        self.assertEqual(r.failed_batches, 2)
        self.assertTrue(all(x["sentiment"] is None for x in db.rows))     # লেখা হয়নি, পরের রানে আবার

    def test_too_large_splits(self):
        calls = []

        class N(SmartNet):
            def post(self, url, headers, payload, timeout):
                size = len(json.loads(payload["messages"][1]["content"].split("\n", 1)[1]))
                calls.append(size)
                return err(413, "Request too large") if size > 3 else ok(answer(payload))
        n = N({"k1": [None]})
        p = GroqPool([("GROQ1", "k1")], post=n.post, now=n.now, sleep=n.sleep)
        db = DB([rev(i) for i in range(1, 9)])
        r = rs.Runner(db, p, CFG, clock=n.now)
        r.run(rs.fetch_pending(db, CFG))
        self.assertTrue(all(x["sentiment"] == 1 for x in db.rows))
        self.assertEqual(calls[0], 8)

    def test_request_cap_and_runtime(self):
        cfg = load_config(override={"sentiment": {"max_requests_per_run": 2}})
        r, db, _ = runner([rev(i) for i in range(1, 60)], {"k1": ["ANSWER"]}, cfg=cfg)
        r.run(rs.fetch_pending(db, cfg))
        self.assertEqual((r.stop, r.requests), ("request_cap", 2))
        cfg = load_config(override={"sentiment": {"max_runtime_seconds": 1}})
        r, db, n = runner([rev(i) for i in range(1, 30)], {"k1": ["ANSWER"]}, cfg=cfg)
        n.t += 5
        r.started = n.t - 5 - 10
        r.run(rs.fetch_pending(db, cfg))
        self.assertEqual(r.stop, "time")

    def test_dry_run_writes_nothing(self):
        r, db, _ = runner([rev(1), rev(2)], {"k1": ["ANSWER"]}, dry_run=True)
        r.run(rs.fetch_pending(db, CFG))
        self.assertEqual((db.updates, len(r.results)), ([], 2))

    def test_max_reviews_per_run(self):
        cfg = load_config(override={"sentiment": {"max_reviews_per_run": 5}})
        self.assertEqual(len(rs.fetch_pending(DB([rev(i) for i in range(1, 20)]), cfg)), 5)

    def test_summary_flags_star_text_mismatch(self):
        r, db, _ = runner([rev(1, "this is bad", 5), rev(2, "okay fine", 1)], {"k1": ["ANSWER"]})
        r.run(rs.fetch_pending(db, CFG))
        s = rs.summarize(r, 2, False)
        self.assertEqual(s["star_text_mismatch"], 2)
        self.assertIn("নমুনা", rs.summary_markdown(s))

    def test_config_validation(self):
        for bad in ({"models": []}, {"batch_size": 0}, {"topics": []}, {"max_wait_seconds": 0}):
            with self.assertRaises(IntelConfigError):
                load_config(override={"sentiment": bad})


if __name__ == "__main__":
    unittest.main()
