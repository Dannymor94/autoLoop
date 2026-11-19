"""Compatibility import: production and contract tests share one hash algorithm."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoloop.evidence import (  # noqa: E402, F401
    canonical_json,
    sha256_canonical,
    suite_fingerprint,
    evidence_key,
    failure_fingerprint,
)
