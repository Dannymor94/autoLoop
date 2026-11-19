# OSS pilot result matrix

Pilot fixture source: `pilot/fixture/` (copy to a dedicated disposable repository and pin baseline SHA before running live candidates).

| Candidate | 1: subscriptions | 2: deterministic | 3: kill/recover | 4: exclusive merge/close | 5: mobile | 6: repair limit |
| --- | --- | --- | --- | --- | --- | --- |
| Bernstein | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| Kandev | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| Cezar | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED |

Requirements 2, 3 and 4 are mandatory. `NOT_TESTED` is never PASS. A live test needs recorded exact version/SHA/config, reproducible command, output/event trace and relevant CI/GitHub link.

Offline mock harness results are **preflight only** and do not change this matrix. QA no-push, stale base SHA and repeated failure checks also need actual autoLoop integration and isolation tests (AL-104).
