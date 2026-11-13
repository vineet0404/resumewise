"""Load test with the standard library only. Many people at once: sign up, save a CV, read it, download their data,
log out and log in again.

    python tests/loadtest.py http://127.0.0.1:8000 --users 100 --threads 25

Run it against YOUR OWN server only. Start that server with BOT_CHECK=0 (the bot check would slow every sign-up on
purpose) and, behind a proxy, with TRUSTED_PROXIES set; sign-up limits are per address, so also set a high
SIGNUPS_PER_IP_PER_DAY and IP_LIMIT_MULTIPLIER for the test, then put the normal values back.
Creates accounts named loadtest-*@example.com: delete them afterwards (Admin shell or a fresh database).
"""
import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

CV = "Aarti Sharma\naarti@example.com\nSKILLS\nPython, Django, SQL\nPROJECTS\nBuilt REST APIs in Django; 300 users"


class Person:
    def __init__(self, base, forwarded=False, number=0):
        self.base = base
        self.forwarded = forwarded
        self.fake_ip = "10.%d.%d.%d" % (number // 65025 % 255, number // 255 % 255, number % 255 + 1)
        self.cookies = {}  # kept by hand: a "Secure" cookie is not sent back over plain http (the local test setup)
        self.opener = urllib.request.build_opener()
        self.csrf = ""
        self.times = []
        self.errors = []

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.forwarded:  # pretend to be a proxy (for a test server that expects https behind one), one address per person
            req.add_header("X-Forwarded-Proto", "https")
            req.add_header("X-Forwarded-For", self.fake_ip)
        if method != "GET":
            req.add_header("X-CSRFToken", self.csrf)
            req.add_header("Referer", (self.base.replace("http://", "https://", 1) if self.forwarded else self.base) + "/")
        if self.cookies:
            req.add_header("Cookie", "; ".join("%s=%s" % kv for kv in self.cookies.items()))
        started = time.time()
        try:
            with self.opener.open(req, timeout=60) as r:
                out, status, headers = r.read(), r.status, r.headers
        except urllib.error.HTTPError as exc:
            out, status, headers = exc.read(), exc.code, exc.headers
        except Exception as exc:  # noqa: BLE001
            self.errors.append("%s %s: %s" % (method, path, exc))
            return 0, {}
        self.times.append((time.time() - started) * 1000)
        for line in headers.get_all("Set-Cookie") or []:
            name, _, rest = line.partition("=")
            value = rest.split(";", 1)[0]
            if value:
                self.cookies[name.strip()] = value
            else:
                self.cookies.pop(name.strip(), None)
        if status >= 400:
            self.errors.append("%s %s -> %d %s" % (method, path, status, out[:120]))
        try:
            return status, json.loads(out)
        except ValueError:
            return status, {}

    def session(self):
        email = "loadtest-%s@example.com" % uuid.uuid4().hex[:12]
        password = "Strong-pass-77x-%s" % uuid.uuid4().hex[:6]
        self.csrf = self.call("GET", "/v1/auth/csrf")[1].get("csrf", "")
        self.call("POST", "/v1/auth/register", {"email": email, "password": password, "name": "Load Test", "accept_terms": True})
        self.csrf = self.call("GET", "/v1/auth/csrf")[1].get("csrf", self.csrf)  # signing in changes the token
        status, made = self.call("POST", "/v1/profiles", {"resume_text": CV})
        if status == 201 or status == 200:
            self.call("GET", "/v1/profiles/%s" % made.get("id"))
            self.call("GET", "/v1/profiles")
        self.call("GET", "/v1/me/export")
        self.call("POST", "/v1/auth/logout", {})
        self.csrf = self.call("GET", "/v1/auth/csrf")[1].get("csrf", "")
        self.call("POST", "/v1/auth/login", {"email": email, "password": password})
        self.csrf = self.call("GET", "/v1/auth/csrf")[1].get("csrf", self.csrf)
        self.call("GET", "/v1/auth/me")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--threads", type=int, default=20)
    ap.add_argument("--forwarded", action="store_true", help="send X-Forwarded-Proto/-For (local test server with TRUSTED_PROXIES=1)")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    people = [Person(base, args.forwarded, i) for i in range(args.users)]
    lock, queue = threading.Lock(), list(people)

    def worker():
        while True:
            with lock:
                if not queue:
                    return
                person = queue.pop()
            person.session()

    started = time.time()
    threads = [threading.Thread(target=worker) for _ in range(args.threads)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    total = time.time() - started
    times = sorted(t for p in people for t in p.times)
    errors = [e for p in people for e in p.errors]
    print("people: %d, requests: %d, took %.1f s (%.1f requests/s)" % (args.users, len(times), total, len(times) / total))
    if times:
        pct = lambda q: times[min(len(times) - 1, int(len(times) * q))]
        print("latency ms: median %.0f, 95%% %.0f, 99%% %.0f, slowest %.0f" % (statistics.median(times), pct(.95), pct(.99), times[-1]))
    print("errors: %d" % len(errors))
    for e in errors[:10]:
        print("  ", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
