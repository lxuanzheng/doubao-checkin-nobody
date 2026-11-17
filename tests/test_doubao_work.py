"""三步链路集成测试：本地假接口模拟 launch → detail → claim → 回查。"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.client import ALREADY, RISK, SUCCESS  # noqa: E402
from src.config import Config  # noqa: E402
from src.doubao_work import DoubaoWorkClient  # noqa: E402


def _detail_payload(checked: bool) -> dict:
    return {
        "code": 0,
        "data": {
            "tasks": [
                {
                    "campaign_code": "daily_signin",
                    "title": "每日签到",
                    "daily_checkin": {
                        "checked_in_today": checked,
                        "continuous_days": 3,
                        "reward": {"reward_amount": 200, "reward_type": "quota_grant"},
                    },
                }
            ]
        },
    }


class _Handler(BaseHTTPRequestHandler):
    scenario = "already"
    claimed = False

    def _send(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)

        if path == "/alice/user/launch":
            self._send({"code": 0, "data": {"ug_campaign_info": {"campaign_group_code": "g1"}}})
            return
        if path == "/alice/ug/campaign/v3/detail/":
            if _Handler.scenario == "claim" and _Handler.claimed:
                self._send(_detail_payload(True))
            elif _Handler.scenario == "already":
                self._send(_detail_payload(True))
            else:
                self._send(_detail_payload(False))
            return
        if path == "/alice/ug/campaign/landing/checkin":
            if _Handler.scenario == "risk":
                self._send({"code": 710010702, "msg": "系统错误"})
            else:
                _Handler.claimed = True
                self._send({"code": 0, "msg": "签到成功"})
            return
        self._send({"code": 404, "msg": "not found"}, 404)

    def log_message(self, *args):  # 静音
        pass


class DoubaoWorkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _client(self) -> DoubaoWorkClient:
        config = Config(
            cookie="sessionid=fake; sessionid_ss=fake",
            base_url=f"http://127.0.0.1:{self.port}",
            headers={"User-Agent": "test-agent"},
            retry_backoff=0.01,
        )
        return DoubaoWorkClient(config)

    def setUp(self):
        _Handler.scenario = "already"
        _Handler.claimed = False

    def test_already_signed(self):
        result = self._client().run()
        self.assertEqual(result.status, ALREADY)
        self.assertTrue(result.ok)
        self.assertEqual(result.amount, "200")
        self.assertEqual(result.streak, 3)

    def test_claim_then_confirm(self):
        _Handler.scenario = "claim"
        result = self._client().run()
        self.assertEqual(result.status, SUCCESS)
        self.assertTrue(result.ok)
        self.assertEqual(result.amount, "200")

    def test_risk_code(self):
        _Handler.scenario = "risk"
        result = self._client().run()
        self.assertEqual(result.status, RISK)
        self.assertFalse(result.ok)

    def test_probe_read_only_does_not_claim(self):
        _Handler.scenario = "claim"
        result = self._client().probe()
        self.assertEqual(result.status, SUCCESS)
        self.assertFalse(_Handler.claimed)  # 只读演练没有提交领取


if __name__ == "__main__":
    unittest.main(verbosity=2)
