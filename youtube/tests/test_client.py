import unittest

import requests

from youtube.client import KeyRejected, QuotaExceeded, YouTubeClient, YouTubeError

SECRET = "AIzaSy-SECRET-KEY-123"


class Resp:
    def __init__(self, status=200, body=None, bad_json=False):
        self.status_code, self._body, self._bad = status, body if body is not None else {}, bad_json

    def json(self):
        if self._bad:
            raise ValueError("no json")
        return self._body


def err(status, reason):
    return Resp(status, {"error": {"code": status, "errors": [{"reason": reason}]}})


class FakeSession:
    def __init__(self, *items):
        self.items, self.calls = list(items), []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        it = self.items.pop(0)
        if isinstance(it, Exception):
            raise it
        return it


def client(*items, retries=2):
    sleeps = []
    s = FakeSession(*items)
    return YouTubeClient(SECRET, session=s, retries=retries, sleep=sleeps.append), s, sleeps


class ClientTest(unittest.TestCase):
    def test_empty_key_rejected(self):
        with self.assertRaises(KeyRejected):
            YouTubeClient("")

    def test_search_returns_video_ids_and_sends_params(self):
        c, s, _ = client(Resp(200, {"items": [{"id": {"videoId": "a"}}, {"id": {"kind": "youtube#channel"}}, {"id": {"videoId": "b"}}]}))
        ids = c.search("air fryer", "2026-10-23T00:00:00Z", "BD", 25, "en", "viewCount")
        self.assertEqual(ids, ["a", "b"])
        url, p = s.calls[0]
        self.assertTrue(url.endswith("/youtube/v3/search"))
        self.assertEqual((p["q"], p["regionCode"], p["type"], p["maxResults"], p["order"], p["relevanceLanguage"]),
                         ("air fryer", "BD", "video", 25, "viewCount", "en"))
        self.assertEqual(p["publishedAfter"], "2026-10-23T00:00:00Z")
        self.assertEqual(p["key"], SECRET)

    def test_max_results_clamped_to_50(self):
        c, s, _ = client(Resp(200, {"items": []}))
        c.search("x", "2026-10-23T00:00:00Z", "BD", 500)
        self.assertEqual(s.calls[0][1]["maxResults"], 50)

    def test_videos_parse_hidden_views_as_none(self):
        c, s, _ = client(Resp(200, {"items": [
            {"id": "a", "snippet": {"title": "T1", "channelTitle": "C1", "publishedAt": "2026-11-01T00:00:00Z"}, "statistics": {"viewCount": "1200"}},
            {"id": "b", "snippet": {"title": "T2"}, "statistics": {}},
        ]}))
        v = c.videos(["a", "b"])
        self.assertEqual([x["views"] for x in v], [1200, None])
        self.assertEqual(v[0]["channel"], "C1")
        self.assertEqual(s.calls[0][1]["id"], "a,b")

    def test_videos_empty_ids_makes_no_request(self):
        c, s, _ = client()
        self.assertEqual(c.videos([]), [])
        self.assertEqual(s.calls, [])

    def test_quota_exceeded(self):
        c, _, _ = client(err(403, "quotaExceeded"))
        with self.assertRaises(QuotaExceeded):
            c.search("x", "2026-10-23T00:00:00Z", "BD", 5)

    def test_key_invalid_and_api_not_enabled(self):
        for status, reason in ((400, "keyInvalid"), (403, "accessNotConfigured"), (401, "")):
            c, _, _ = client(err(status, reason) if reason else Resp(401, {}))
            with self.assertRaises(KeyRejected):
                c.search("x", "2026-10-23T00:00:00Z", "BD", 5)

    def test_retries_server_error_then_succeeds(self):
        c, s, sleeps = client(Resp(503), Resp(200, {"items": [{"id": {"videoId": "a"}}]}))
        self.assertEqual(c.search("x", "2026-10-23T00:00:00Z", "BD", 5), ["a"])
        self.assertEqual(len(s.calls), 2)
        self.assertEqual(sleeps, [1])

    def test_gives_up_after_retries(self):
        c, s, _ = client(Resp(500), Resp(500), Resp(500))
        with self.assertRaisesRegex(YouTubeError, "500"):
            c.search("x", "2026-10-23T00:00:00Z", "BD", 5)
        self.assertEqual(len(s.calls), 3)

    def test_non_retryable_error_not_retried(self):
        c, s, _ = client(err(404, "notFound"))
        with self.assertRaisesRegex(YouTubeError, "404"):
            c.videos(["a"])
        self.assertEqual(len(s.calls), 1)

    def test_network_error_message_never_contains_key_or_url(self):
        boom = requests.ConnectionError(f"HTTPSConnectionPool: url: /youtube/v3/search?q=x&key={SECRET}")
        c, _, _ = client(boom, boom, boom)
        with self.assertRaises(YouTubeError) as cm:
            c.search("x", "2026-10-23T00:00:00Z", "BD", 5)
        msg = str(cm.exception)
        self.assertNotIn(SECRET, msg)
        self.assertNotIn("key=", msg)
        self.assertIsNone(cm.exception.__cause__)
        self.assertTrue(cm.exception.__suppress_context__)

    def test_bad_json_is_a_clean_error(self):
        c, _, _ = client(Resp(200, bad_json=True))
        with self.assertRaisesRegex(YouTubeError, "JSON"):
            c.search("x", "2026-10-23T00:00:00Z", "BD", 5)


if __name__ == "__main__":
    unittest.main()
