import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from trends.fetcher import CircuitOpen, FetchFailed, Fetcher, PytrendsClient, RateLimited
from trends.config import load_config

S = dict(load_config()["settings"])


class Script:
    """ক্রমানুসারে ফল/ত্রুটি ফেরত দেয়।"""

    def __init__(self, *steps):
        self.steps, self.calls = list(steps), []

    def interest(self, keywords, timeframe):
        self.calls.append((list(keywords), timeframe))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def fetcher(client, **over):
    sleeps = []
    f = Fetcher(client, {**S, **over}, sleep=sleeps.append, rand=lambda: 0.5)
    return f, sleeps


class FetcherTests(unittest.TestCase):
    def test_success_and_pacing(self):
        c = Script({"a": []}, {"b": []})
        f, sleeps = fetcher(c)
        f.get(["a"], "x")
        self.assertEqual(sleeps, [])                       # প্রথম রিকোয়েস্টের আগে বিরতি নেই
        f.get(["b"], "x")
        self.assertEqual(sleeps, [S["delay_seconds"] + S["jitter_seconds"] * 0.5])
        self.assertEqual(f.stats, {"requests": 2, "ok": 2, "rate_limited": 0, "failed": 0})

    def test_rate_limit_backs_off_then_succeeds(self):
        c = Script(RateLimited("429"), RateLimited("429"), {"a": []})
        f, sleeps = fetcher(c, block_limit=5)
        self.assertEqual(f.get(["a"], "x"), {"a": []})
        self.assertIn(S["backoff_seconds"], sleeps)                 # প্রথম ব্যাকঅফ
        self.assertIn(S["backoff_seconds"] * 2, sleeps)             # দ্বিগুণ
        self.assertEqual(f.stats["rate_limited"], 2)

    def test_gives_up_after_retries(self):
        c = Script(FetchFailed("boom"), FetchFailed("boom"), FetchFailed("boom"))
        f, _ = fetcher(c)
        with self.assertRaises(FetchFailed):
            f.get(["a"], "x")
        self.assertEqual(len(c.calls), S["max_retries"] + 1)

    def test_circuit_opens_after_consecutive_rate_limits(self):
        c = Script(*[RateLimited("429")] * 10)
        f, _ = fetcher(c, block_limit=3)
        with self.assertRaises(CircuitOpen):
            f.get(["a"], "x")
        self.assertTrue(f.circuit_open)
        n = len(c.calls)
        with self.assertRaises(CircuitOpen):                        # খোলা সার্কিটে আর রিকোয়েস্ট যায় না
            f.get(["b"], "x")
        self.assertEqual(len(c.calls), n)

    def test_success_resets_circuit_counter(self):
        c = Script(RateLimited("429"), {"a": []}, RateLimited("429"), {"b": []})
        f, _ = fetcher(c, block_limit=2)
        f.get(["a"], "x")
        f.get(["b"], "x")
        self.assertFalse(f.circuit_open)


def _timeline(n=6, partial_last=True, values=(10, 20)):
    first = datetime(2026, 9, 27, tzinfo=timezone.utc)      # রবিবার
    rows = []
    for k in range(n):
        t = int((first + timedelta(weeks=k)).timestamp())
        row = {"time": str(t), "formattedTime": "x", "formattedAxisTime": "x",
               "value": [v + k for v in values], "hasData": [True] * len(values)}
        if partial_last and k == n - 1:
            row["isPartial"] = True
        rows.append(row)
    return {"default": {"timelineData": rows}}


try:
    import pytrends  # noqa: F401
    HAVE_PYTRENDS = True
except Exception:  # noqa: BLE001
    HAVE_PYTRENDS = False


@unittest.skipUnless(HAVE_PYTRENDS, "pytrends ইনস্টল নেই")
class PytrendsClientTests(unittest.TestCase):
    """আসল pytrends কোড, শুধু নেটওয়ার্ক নকল। এতে pytrends + আপনার pandas সংস্করণের সামঞ্জস্য যাচাই হয়।"""

    def _client(self, payload):
        from pytrends.request import TrendReq

        def fake_get_data(self_, url, method="get", trim_chars=0, **kw):
            if url == TrendReq.GENERAL_URL:
                return {"widgets": [{"id": "TIMESERIES", "token": "t", "request": {}}]}
            if isinstance(payload, Exception):
                raise payload
            return payload

        p1 = mock.patch.object(TrendReq, "GetGoogleCookie", lambda self_: {})
        p2 = mock.patch.object(TrendReq, "_get_data", fake_get_data)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        return PytrendsClient()

    def test_parses_values_dates_and_partial_flag(self):
        out = self._client(_timeline()).interest(["a", "b"], "today 12-m")
        self.assertEqual([p[1] for p in out["a"]], [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        self.assertEqual([p[1] for p in out["b"]], [20.0, 21.0, 22.0, 23.0, 24.0, 25.0])
        self.assertEqual(out["a"][0][0], date(2026, 9, 27))
        self.assertEqual([p[2] for p in out["a"]], [False] * 5 + [True])

    def test_no_partial_column(self):
        out = self._client(_timeline(partial_last=False)).interest(["a", "b"], "today 12-m")
        self.assertFalse(any(p[2] for p in out["a"]))

    def test_empty_response(self):
        out = self._client({"default": {"timelineData": []}}).interest(["a"], "today 12-m")
        self.assertEqual(out, {"a": []})

    def test_429_becomes_rate_limited(self):
        from pytrends.exceptions import TooManyRequestsError
        err = TooManyRequestsError("The request failed: Google returned a response with code 429", None)
        with self.assertRaises(RateLimited):
            self._client(err).interest(["a"], "today 12-m")

    def test_other_errors_become_fetch_failed(self):
        with self.assertRaises(FetchFailed) as cm:
            self._client(ValueError("weird")).interest(["a"], "today 12-m")
        self.assertNotIsInstance(cm.exception, RateLimited)

    def test_client_init_failure_is_wrapped(self):
        import requests
        from pytrends.request import TrendReq
        with mock.patch.object(TrendReq, "GetGoogleCookie", side_effect=requests.ConnectionError("blocked")):
            with self.assertRaises(FetchFailed):
                PytrendsClient()


if __name__ == "__main__":
    unittest.main()
