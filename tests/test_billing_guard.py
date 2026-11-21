from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoloop.billing_guard import (  # noqa: E402
    BillingModeRejected, confirmed_subscription_login, inspect_claude_settings,
    isolated_subscription_env, subscription_preflight,
)


class BillingGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.worktree = self.root / "worktree"
        self.home.mkdir()
        self.worktree.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def fake_status(stdout: str, code: int = 0):
        def run(argv, **kwargs):
            assert kwargs["timeout"] == 12
            assert kwargs["capture_output"] is True
            assert "ANTHROPIC_API_KEY" not in kwargs["env"]
            return subprocess.CompletedProcess(argv, code, stdout, "")
        return run

    def test_codex_subscription_only_positive(self):
        env = subscription_preflight("codex", home=self.home, worktree=self.worktree, source_env={"PATH": "/bin", "HOME": str(self.home)}, run=self.fake_status("Logged in using ChatGPT\n"))
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")

    def test_claude_subscription_only_positive(self):
        status = json.dumps({"loggedIn": True, "authMethod": "claude.ai"})
        subscription_preflight("claude", home=self.home, worktree=self.worktree, source_env={"PATH": "/bin", "HOME": str(self.home)}, run=self.fake_status(status))

    def test_auth_home_must_match_inspected_home(self):
        for wrong_env in ({"PATH": "/bin"}, {"PATH": "/bin", "HOME": str(self.root)}):
            with self.subTest(wrong_env=wrong_env), self.assertRaisesRegex(BillingModeRejected, "HOME_"):
                subscription_preflight("codex", home=self.home, worktree=self.worktree, source_env=wrong_env, run=self.fake_status("Logged in using ChatGPT"))

    def test_env_api_billing_override_is_blocked_before_auth_check(self):
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK"):
            with self.subTest(key=key), self.assertRaisesRegex(BillingModeRejected, "API_OVERRIDE_ENV"):
                isolated_subscription_env({key: "secret"})

    def test_github_and_shell_auth_removed_from_child(self):
        env = isolated_subscription_env({"GITHUB_TOKEN": "sensitive", "SSH_AUTH_SOCK": "/tmp/agent", "PATH": "/bin"})
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("SSH_AUTH_SOCK", env)

    def test_custom_codex_provider_is_blocked(self):
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir()
        for content in ('model_provider = "custom_gateway"\n', '[model_providers.custom_gateway]\nbase_url = "https://example.invalid"\n'):
            config.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(BillingModeRejected, "CUSTOM_CODEX_PROVIDER"):
                subscription_preflight("codex", home=self.home, worktree=self.worktree, source_env={"PATH": "/bin", "HOME": str(self.home)}, run=self.fake_status("Logged in using ChatGPT"))

    def test_api_key_helper_and_nested_env_are_blocked(self):
        settings = self.worktree / ".claude" / "settings.local.json"
        settings.parent.mkdir()
        for doc in ({"apiKeyHelper": "my-helper"}, {"env": {"ANTHROPIC_API_KEY": "somekey"}}):
            settings.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(BillingModeRejected):
                inspect_claude_settings(home=self.home, worktree=self.worktree)

    def test_malformed_or_symlinked_settings_are_blocked(self):
        settings = self.home / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text("{bad", encoding="utf-8")
        with self.assertRaisesRegex(BillingModeRejected, "INVALID_SETTINGS"):
            inspect_claude_settings(home=self.home, worktree=self.worktree)
        settings.unlink()
        real = self.root / "real.json"
        real.write_text("{}", encoding="utf-8")
        settings.symlink_to(real)
        with self.assertRaisesRegex(BillingModeRejected, "UNTRUSTED_SETTINGS"):
            inspect_claude_settings(home=self.home, worktree=self.worktree)

    def test_unrecognized_status_and_api_login_fail_closed(self):
        cases = [
            ("codex", "Logged in using an API key"),
            ("codex", "Not logged in"),
            ("codex", "Logged in using ChatGPT, maybe"),
            ("claude", '{"loggedIn": true, "authMethod": "api_key"}'),
            ("claude", "not-json"),
        ]
        for provider, result in cases:
            with self.subTest(provider=provider, result=result), self.assertRaises(BillingModeRejected):
                confirmed_subscription_login(provider, run=self.fake_status(result), env={})

    def test_status_nonzero_and_unknown_provider_blocked(self):
        with self.assertRaises(BillingModeRejected):
            confirmed_subscription_login("codex", run=self.fake_status("", code=1), env={})
        with self.assertRaises(BillingModeRejected):
            confirmed_subscription_login("other", run=self.fake_status(""), env={})


if __name__ == "__main__":
    unittest.main()
