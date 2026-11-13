import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from core import gateway, providers

SEEN = {}


class _Handler(BaseHTTPRequestHandler):
    mode = "ok"

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN["headers"], SEEN["body"] = {k.lower(): v for k, v in self.headers.items()}, body
        if _Handler.mode == "401":
            self.send_response(401); self.end_headers(); self.wfile.write(b"{}"); return
        if _Handler.mode == "500":
            self.send_response(500); self.end_headers(); self.wfile.write(b'{"secret":"sk-leak"}'); return
        reply = {"content": [{"type": "text", "text": '{"ok": true}'}], "usage": {"input_tokens": 1000, "output_tokens": 500}}
        data = json.dumps(reply).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass


class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/v1/messages" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def make(self):
        return providers.AnthropicProvider("sk-test-key", url=self.url, sleep=lambda s: None)

    def test_request_shape_reply_and_cost(self):
        _Handler.mode = "ok"
        result = self.make().complete("sys", "hello")
        self.assertEqual(result.text, '{"ok": true}')
        self.assertEqual(SEEN["headers"]["x-api-key"], "sk-test-key")
        self.assertEqual(SEEN["headers"]["anthropic-version"], providers.API_VERSION)
        self.assertEqual(SEEN["body"]["system"], "sys")
        self.assertEqual(SEEN["body"]["messages"], [{"role": "user", "content": "hello"}])
        # 1000*30000 + 500*150000 = 105,000,000 / 1,000,000 = 105 paise
        self.assertEqual(result.cost_paise, 105)

    def test_server_error_is_safe_and_key_hidden(self):
        _Handler.mode = "500"
        provider = self.make()
        with self.assertRaises(gateway.GatewayError) as ctx:
            provider.complete("s", "u")
        self.assertNotIn("sk-", str(ctx.exception))
        self.assertNotIn("sk-test-key", repr(provider))
        _Handler.mode = "ok"

    def test_401_says_key_rejected(self):
        _Handler.mode = "401"
        with self.assertRaises(gateway.GatewayError) as ctx:
            self.make().complete("s", "u")
        self.assertIn("key was rejected", str(ctx.exception))
        _Handler.mode = "ok"

    def test_unreachable_server(self):
        bad = providers.AnthropicProvider("k", url="http://127.0.0.1:9/x", timeout=1, sleep=lambda s: None)
        with self.assertRaises(gateway.GatewayError):
            bad.complete("s", "u")

    def test_env_factory(self):
        self.assertIsNone(providers.provider_from_env({}))
        key = "sk-ant-" + "x" * 40
        p = providers.provider_from_env({"ANTHROPIC_API_KEY": " " + key + " ", "AI_MODEL": "m"})
        self.assertEqual(p.model, "m")
        for bad in ("teri-key-yahan", "sk-ant-teri-asli-key", "yahan-paste-karo-apni-copy-ki-hui-key"):
            with self.assertRaises(gateway.GatewayError):
                providers.provider_from_env({"ANTHROPIC_API_KEY": bad})

    def test_gateway_accepts_fenced_json(self):
        g = gateway.Gateway({"t": gateway.FakeProvider(['Here you go:\n```json\n{"a": 1}\n```'])})
        self.assertEqual(g.run("t", "x", {}), {"a": 1})


if __name__ == "__main__":
    unittest.main()
