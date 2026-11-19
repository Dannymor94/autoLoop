"""AL-106 local API/UI contract tests. Real Android + private tunnel NOT_TESTED."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoloop.api import COOKIE_NAME, create_app  # noqa: E402
from autoloop.database import create_database_engine, migrate, sqlite_url  # noqa: E402
from autoloop.dispatcher import Dispatcher  # noqa: E402


class MobileAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        url = sqlite_url(Path(self.temp.name) / "api.sqlite")
        migrate(url)
        self.engine = create_database_engine(url)
        self.dispatcher = Dispatcher(self.engine)
        self.dispatcher.add_project(project_id="P", name="Mobile")
        self.dispatcher.add_plan(plan_id="PL", project_id="P", spec_hash="a" * 64)
        self.dispatcher.add_task(task_id="A", plan_id="PL", title="Task", acceptance_spec_hash="b" * 64)
        self.app = create_app(self.engine, owner_password="test-owner-password-very-long", secure_cookie=False)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def auth(self) -> str:
        self.assertEqual(self.client.post("/api/login", json={"password": "test-owner-password-very-long"}).status_code, 200)
        session = self.client.get("/api/session")
        self.assertEqual(session.status_code, 200)
        return session.json()["csrf_token"]

    def test_password_is_required_for_app_boot(self) -> None:
        with self.assertRaisesRegex(ValueError, "AUTOLOOP_UI_PASSWORD_REQUIRED"):
            create_app(self.engine, owner_password="weak")

    def test_unauthenticated_state_is_private(self) -> None:
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)
        self.assertEqual(self.client.get("/api/tasks/A/events").status_code, 401)
        self.assertEqual(self.client.post("/api/tasks/A/stop", json={"idempotency_key": "stop-12345"}).status_code, 401)
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})

    def test_login_and_httponly_cookie(self) -> None:
        result = self.client.post("/api/login", json={"password": "test-owner-password-very-long"})
        self.assertEqual(result.status_code, 200)
        self.assertIn("httponly", result.headers["set-cookie"].lower())
        self.assertIn("samesite=strict", result.headers["set-cookie"].lower())
        self.assertNotIn("; secure", result.headers["set-cookie"].lower())  # loopback HTTP only
        self.assertIn(COOKIE_NAME, self.client.cookies)
        self.assertEqual(len(self.client.get("/api/tasks").json()), 1)

    def test_wrong_login_is_rate_limited(self) -> None:
        for _ in range(5):
            self.assertEqual(self.client.post("/api/login", json={"password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={"password": "wrong"}).status_code, 429)

    def test_stop_pending_cannot_fake_confirmed_state(self) -> None:
        self.dispatcher.claim_next(worker_id="worker", idempotency_key="start")
        csrf = self.auth()
        response = self.client.post("/api/tasks/A/stop", json={"idempotency_key": "owner-stop-1"}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "STOP_PENDING")
        self.assertEqual(self.client.get("/api/tasks").json()[0]["state"], "RUNNING")

    def test_csrf_and_origin_required_for_write(self) -> None:
        self.dispatcher.claim_next(worker_id="worker", idempotency_key="start")
        csrf = self.auth()
        self.assertEqual(self.client.post("/api/tasks/A/stop", json={"idempotency_key": "owner-stop-1"}).status_code, 403)
        self.assertEqual(self.client.post("/api/tasks/A/stop", json={"idempotency_key": "owner-stop-1"}, headers={"X-CSRF-Token": csrf, "Origin": "https://attacker.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/tasks").json()[0]["state"], "RUNNING")

    def test_confirmed_stop_resume_roundtrip(self) -> None:
        claim = self.dispatcher.claim_next(worker_id="worker", idempotency_key="start")
        csrf = self.auth()
        stop = self.client.post("/api/tasks/A/stop", json={"idempotency_key": "owner-stop-1"}, headers={"X-CSRF-Token": csrf}).json()
        self.dispatcher.confirm_stop(request_id=stop["request_id"], task_id="A", attempt_id=claim["attempt_id"], fencing_token=1, checkpoint_hash="a" * 64)
        res = self.client.post("/api/tasks/A/resume", json={"idempotency_key": "owner-resume-1"}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["state"], "READY")

    def test_logout_revokes_session(self) -> None:
        csrf = self.auth()
        self.assertEqual(self.client.post("/api/logout", headers={"X-CSRF-Token": csrf}).status_code, 200)
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)

    def test_ui_assets_have_no_embedded_tokens_and_csp(self) -> None:
        response = self.client.get("/ui/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        javascript = self.client.get("/ui/app.js")
        self.assertEqual(javascript.status_code, 200)
        self.assertNotIn("localStorage.setItem", javascript.text)
        self.assertNotIn("dangerously-skip", javascript.text)


if __name__ == "__main__":
    unittest.main()
