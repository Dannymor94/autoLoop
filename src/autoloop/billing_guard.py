"""Fail-closed *preflight* for subscription-only CLI attempts.

This is an additional guard, not proof that the vendor cannot change billing
server-side. Smoke A must verify the exact installed CLI versions and managed
settings on the owner's Mac before an attempt is authorized.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tomllib
from typing import Callable, Mapping


class BillingModeRejected(RuntimeError):
    """Never fall back to an API account or pay-as-you-go."""


API_OVERRIDE_KEYS = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_API_KEY",
    "AWS_BEARER_TOKEN_BEDROCK", "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "AZURE_OPENAI_API_KEY", "OPENAI_IDENTITY_TOKEN_FILE",
    "CLAUDE_CONFIG_DIR", "CODEX_HOME",
})


def isolated_subscription_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Reject an ambiguous parent *and* strip billing overrides from child.

    Rejecting rather than silently fixing prevents reporting subscription-only
    status while the owner has unknowingly configured a paid provider.
    """
    original = dict(os.environ if source is None else source)
    collisions = sorted(k for k in API_OVERRIDE_KEYS if original.get(k))
    if collisions:
        raise BillingModeRejected("BILLING_MODE:API_OVERRIDE_ENV:" + ",".join(collisions))
    child = {k: v for k, v in original.items() if k not in API_OVERRIDE_KEYS}
    for k in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT", "GIT_ASKPASS", "SSH_ASKPASS", "SSH_AUTH_SOCK", "GIT_SSH_COMMAND"):
        child.pop(k, None)
    child["GIT_TERMINAL_PROMPT"] = "0"
    return child


def _reject_unsafe_settings(data: object, *, label: str) -> None:
    """Inspect nested configuration; never print a secret or file content."""
    if isinstance(data, dict):
        for name, value in data.items():
            if name == "apiKeyHelper" and value:
                raise BillingModeRejected(f"BILLING_MODE:API_KEY_HELPER:{label}")
            if name in API_OVERRIDE_KEYS and value:
                raise BillingModeRejected(f"BILLING_MODE:API_OVERRIDE_SETTINGS:{label}")
            _reject_unsafe_settings(value, label=label)
    elif isinstance(data, list):
        for item in data:
            _reject_unsafe_settings(item, label=label)


def inspect_claude_settings(*, home: Path, worktree: Path, managed_paths: tuple[Path, ...] = ()) -> None:
    """Inspect known local scopes. Smoke A must establish effective precedence.

    The caller is responsible for listing all managed settings sources on the
    target host; if that completeness cannot be proved, block externally.
    """
    paths = (
        home / ".claude" / "settings.json",
        worktree / ".claude" / "settings.json",
        worktree / ".claude" / "settings.local.json",
        *managed_paths,
    )
    for path in paths:
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file():
            raise BillingModeRejected("BILLING_MODE:UNTRUSTED_SETTINGS")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BillingModeRejected("BILLING_MODE:INVALID_SETTINGS") from exc
        if not isinstance(data, dict):
            raise BillingModeRejected("BILLING_MODE:INVALID_SETTINGS")
        _reject_unsafe_settings(data, label=path.name)


def inspect_codex_settings(*, home: Path, worktree: Path) -> None:
    """Reject explicit custom model/API providers in known Codex scopes."""
    for path in (home / ".codex" / "config.toml", worktree / ".codex" / "config.toml"):
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file():
            raise BillingModeRejected("BILLING_MODE:UNTRUSTED_SETTINGS")
        try:
            settings = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BillingModeRejected("BILLING_MODE:INVALID_SETTINGS") from exc
        _reject_unsafe_settings(settings, label=path.name)
        if settings.get("model_provider") not in (None, "openai") or settings.get("model_providers") or settings.get("profile"):
            raise BillingModeRejected("BILLING_MODE:CUSTOM_CODEX_PROVIDER")


def confirmed_subscription_login(provider: str, *, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run, env: Mapping[str, str]) -> None:
    """Positive evidence only; unknown CLI versions/output must fail closed.

    The status check does *not* authorize launch by itself. It must be paired
    with effective-settings checks and a pinned CLI version from Smoke A.
    """
    if provider == "claude":
        argv = ["claude", "auth", "status", "--json"]
    elif provider == "codex":
        argv = ["codex", "login", "status"]
    else:
        raise BillingModeRejected("BILLING_MODE:UNKNOWN_PROVIDER")
    try:
        check = run(argv, text=True, capture_output=True, timeout=12, env=dict(env), check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BillingModeRejected("BILLING_MODE:AUTH_STATUS_UNAVAILABLE") from exc
    if check.returncode != 0:
        raise BillingModeRejected("BILLING_MODE:AUTH_STATUS_UNAVAILABLE")
    if provider == "codex":
        if check.stdout.strip() != "Logged in using ChatGPT":
            raise BillingModeRejected("BILLING_MODE:NOT_CHATGPT_SUBSCRIPTION")
    else:
        try:
            status = json.loads(check.stdout)
        except ValueError as exc:
            raise BillingModeRejected("BILLING_MODE:UNKNOWN_CLAUDE_AUTH") from exc
        # Keep a strict and deliberately small vocabulary. Confirm installed
        # CLI output on Mac before allowing the real launch to use this gate.
        if not isinstance(status, dict) or status.get("loggedIn") is not True or status.get("authMethod") not in {"claude.ai", "oauth"}:
            raise BillingModeRejected("BILLING_MODE:NOT_CLAUDE_SUBSCRIPTION")


def subscription_preflight(provider: str, *, home: Path, worktree: Path, managed_paths: tuple[Path, ...] = (), source_env: Mapping[str, str] | None = None, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> dict[str, str]:
    env = isolated_subscription_env(source_env)
    if provider == "claude":
        inspect_claude_settings(home=home, worktree=worktree, managed_paths=managed_paths)
    elif provider == "codex":
        inspect_codex_settings(home=home, worktree=worktree)
    else:
        raise BillingModeRejected("BILLING_MODE:UNKNOWN_PROVIDER")
    confirmed_subscription_login(provider, run=run, env=env)
    return env
