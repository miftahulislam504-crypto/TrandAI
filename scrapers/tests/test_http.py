"""PoliteClient ও RobotsCache-এর টেস্ট (নকল session দিয়ে, নেটওয়ার্ক ছাড়া)।"""
import unittest

import requests

from scrapers.common.http import (BlockedError, CircuitOpen, FetchError, PoliteClient,
                                  RobotsDisallowed, looks_blocked)
from scrapers.common.robots import RobotsCache, parse_robots, robots_allowed


class FakeResponse:
    def __init__(self, status=200, text="", headers=None, json_data=None, body=None):
        self.status_code, self.text = status, text
        self.body = body
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.encoding = "utf-8"
        self._json = json_data

    @property
    def content(self):
        return self.text.encode()

    def iter_content(self, size):
        data = self.body if self.body is not None else self.text.encode()
        for i in range(0, len(data), size):
            yield data[i:i + size]

    def close(self):
        pass

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    """routes: {url-এর অংশ: FakeResponse | [FakeResponse...] | Exception}"""

    def __init__(self, routes):
        self.routes, self.headers, self.calls = routes, {}, []

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=True, stream=False):
        full = requests.Request("GET", url, params=params).prepare().url
        self.calls.append(full)
        for key, val in self.routes.items():
            if key in full:
                if isinstance(val, list):
                    val = val.pop(0) if len(val) > 1 else val[0]
                if isinstance(val, Exception):
                    raise val
                return val
        return FakeResponse(404, "not found")


def make(routes, **kw):
    sleeps = []
    c = PoliteClient(session=FakeSession(routes), sleep=sleeps.append, rand=lambda: 0.5, delay=2.0, jitter=1.0, **kw)
    return c, sleeps


ROBOTS = "User-agent: *\nDisallow: /private/\nDisallow: /*?secret=\n"


class RobotsCacheTests(unittest.TestCase):
    def test_modes(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return {"https://a.com/robots.txt": (200, ROBOTS), "https://b.com/robots.txt": (404, ""),
                    "https://c.com/robots.txt": (503, ""), "https://d.com/robots.txt": (None, "")}[url]

        rc = RobotsCache(fetch)
        self.assertTrue(rc.allowed("https://a.com/ok"))
        self.assertFalse(rc.allowed("https://a.com/private/x"))
        self.assertFalse(rc.allowed("https://a.com/p?secret=1"))
        self.assertTrue(rc.allowed("https://b.com/anything"))   # 404 = নিষেধ নেই
        self.assertFalse(rc.allowed("https://c.com/anything"))  # 5xx = সাবধানতায় নিষেধ
        self.assertFalse(rc.allowed("https://d.com/anything"))  # নেটওয়ার্ক ত্রুটি = নিষেধ
        self.assertEqual(len(calls), 4)  # হোস্টপ্রতি একবার

    def test_specific_agent(self):
        g = parse_robots("User-agent: marketresearchbot\nDisallow: /\n\nUser-agent: *\nDisallow:\n")
        self.assertFalse(robots_allowed(g, "/x"))


class ClientTests(unittest.TestCase):
    def test_success_and_delay(self):
        c, sleeps = make({"/robots.txt": FakeResponse(200, ROBOTS), "/page": FakeResponse(200, "<html>ok</html>")})
        r = c.get("https://a.com/page")
        self.assertEqual(r.text, "<html>ok</html>")
        self.assertEqual(c.stats["ok"], 1)
        # ১ম রিকোয়েস্ট (robots) বিরতিহীন, ২য়টার আগে delay + jitter*0.5 = 2.5
        self.assertEqual(sleeps, [2.5])

    def test_robots_disallowed_makes_no_request(self):
        s = FakeSession({"/robots.txt": FakeResponse(200, ROBOTS)})
        c = PoliteClient(session=s, sleep=lambda x: None)
        with self.assertRaises(RobotsDisallowed):
            c.get("https://a.com/private/data")
        self.assertEqual(c.stats["robots_skipped"], 1)
        self.assertFalse([u for u in s.calls if "/private/" in u])

    def test_block_detection(self):
        self.assertTrue(looks_blocked(403, ""))
        self.assertTrue(looks_blocked(429, ""))
        self.assertTrue(looks_blocked(200, "<html>Just a moment...</html>"))
        self.assertFalse(looks_blocked(200, "<html>captcha field in login form</html>"))
        self.assertFalse(looks_blocked(200, "x5secdata " + "a" * 60_000))  # বড় পেজ = স্বাভাবিক

    def test_circuit_breaker(self):
        c, _ = make({"/robots.txt": FakeResponse(404), "/p": FakeResponse(403, "denied")}, block_limit=3)
        for _ in range(3):
            with self.assertRaises(BlockedError):
                c.get("https://a.com/p")
        self.assertTrue(c.circuit_open)
        before = c.stats["requests"]
        with self.assertRaises(CircuitOpen):
            c.get("https://a.com/p")
        self.assertEqual(c.stats["requests"], before)  # আর কোনো রিকোয়েস্ট যায়নি

    def test_success_resets_block_counter(self):
        c, _ = make({"/robots.txt": FakeResponse(404),
                     "/p": [FakeResponse(429), FakeResponse(200, "fine")]}, block_limit=2)
        with self.assertRaises(BlockedError):
            c.get("https://a.com/p")
        self.assertEqual(c.get("https://a.com/p").text, "fine")
        self.assertFalse(c.circuit_open)

    def test_retry_on_5xx_then_ok(self):
        c, sleeps = make({"/robots.txt": FakeResponse(404),
                          "/p": [FakeResponse(502), FakeResponse(200, "ok")]})
        self.assertEqual(c.get("https://a.com/p").text, "ok")
        self.assertEqual(c.stats["errors"], 1)

    def test_retry_exhausted(self):
        c, _ = make({"/robots.txt": FakeResponse(404), "/p": requests.ConnectionError("down")}, max_retries=1)
        with self.assertRaises(FetchError):
            c.get("https://a.com/p")
        self.assertEqual(c.stats["errors"], 2)

    def test_get_json(self):
        c, _ = make({"/robots.txt": FakeResponse(404),
                     "/j": FakeResponse(200, "{}", json_data={"a": 1}), "/bad": FakeResponse(200, "<html>")})
        self.assertEqual(c.get_json("https://a.com/j"), {"a": 1})
        with self.assertRaises(FetchError):
            c.get_json("https://a.com/bad")

    def test_params_checked_against_robots(self):
        c, _ = make({"/robots.txt": FakeResponse(200, ROBOTS), "/ok": FakeResponse(200, "x")})
        with self.assertRaises(RobotsDisallowed):
            c.get("https://a.com/ok", params={"secret": "1"})



class GetBytesTests(unittest.TestCase):
    IMG = "https://cdn.example.com/p/a.jpg"

    def test_returns_body_and_uses_delay_and_robots(self):
        c, sleeps = make({"robots.txt": FakeResponse(200, "User-agent: *\nDisallow: /private/\n"),
                          "a.jpg": FakeResponse(200, body=b"\xff\xd8jpegdata")})
        self.assertEqual(c.get_bytes(self.IMG), b"\xff\xd8jpegdata")
        self.assertEqual(c.stats["ok"], 1)
        self.assertTrue(any(s >= 2.0 for s in sleeps))           # robots আনার পরে ছবির আগেও বিরতি
        with self.assertRaises(RobotsDisallowed):
            c.get_bytes("https://cdn.example.com/private/x.jpg")

    def test_too_big_raises_fetch_error(self):
        c, _ = make({"a.jpg": FakeResponse(200, body=b"x" * 5000)}, respect_robots=False)
        with self.assertRaises(FetchError):
            c.get_bytes(self.IMG, max_bytes=1000)

    def test_block_counts_toward_circuit(self):
        c, _ = make({"a.jpg": FakeResponse(403, body=b"")}, respect_robots=False, block_limit=2)
        for _ in range(2):
            with self.assertRaises(BlockedError):
                c.get_bytes(self.IMG)
        with self.assertRaises(CircuitOpen):
            c.get_bytes(self.IMG)

    def test_404_is_plain_error_not_a_block(self):
        c, _ = make({"a.jpg": FakeResponse(404, body=b"")}, respect_robots=False)
        with self.assertRaises(FetchError):
            c.get_bytes(self.IMG)
        self.assertFalse(c.circuit_open)
        self.assertEqual(c.stats["blocked"], 0)

    def test_5xx_retries_then_succeeds(self):
        c, _ = make({"a.jpg": [FakeResponse(503, body=b""), FakeResponse(200, body=b"ok")]}, respect_robots=False)
        self.assertEqual(c.get_bytes(self.IMG), b"ok")
        self.assertEqual(c.stats["errors"], 1)

    def test_network_error_exhausts_retries(self):
        c, _ = make({"a.jpg": requests.ConnectionError("down")}, respect_robots=False, max_retries=1)
        with self.assertRaises(FetchError):
            c.get_bytes(self.IMG)
        self.assertEqual(c.stats["errors"], 2)


if __name__ == "__main__":
    unittest.main()
