"""Run with PYTHONPATH=src python -m autoloop <command>."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

from autoloop.api import create_app
from autoloop.database import create_database_engine, migrate, sqlite_url
from autoloop.dispatcher import DispatchRejected, Dispatcher
from autoloop.owner_time import OwnerTimeLedger, OwnerTimeRejected


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description="autoLoop deterministic owner dispatcher")
    top.add_argument("--db", type=Path, default=Path("data/autoloop.sqlite"), help="SQLite DB file; persisted across restarts")
    actions = top.add_subparsers(dest="action", required=True)
    actions.add_parser("init-db")
    p = actions.add_parser("add-project")
    p.add_argument("--id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--repo-url")
    p = actions.add_parser("add-plan")
    p.add_argument("--id", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--spec-hash", required=True)
    p = actions.add_parser("add-task")
    p.add_argument("--id", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--acceptance-hash", required=True)
    p.add_argument("--instructions-file", type=Path)
    p.add_argument("--depends-on", action="append", default=[])
    p = actions.add_parser("claim")
    p.add_argument("--worker", required=True)
    p.add_argument("--key", default=None)
    actions.add_parser("tasks")
    p = actions.add_parser("events")
    p.add_argument("--task", required=True)
    p = actions.add_parser("stop")
    p.add_argument("--task", required=True)
    p.add_argument("--key", default=None)
    p = actions.add_parser("resume")
    p.add_argument("--task", required=True)
    p.add_argument("--key", default=None)
    p = actions.add_parser("serve")
    p.add_argument("--port", type=int, default=8765)
    p = actions.add_parser("time", help="Owner-measured active time; no model invocation")
    p.add_argument("time_action", choices=("start", "stop", "summary"))
    p.add_argument("task_id")
    p.add_argument("--ledger", type=Path, default=Path("data/owner-time.jsonl"))
    p.add_argument("--key", default=None)
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.action == "time":
        try:
            ledger = OwnerTimeLedger(args.ledger)
            result = ledger.summary(args.task_id) if args.time_action == "summary" else ledger.record(task_id=args.task_id, action=args.time_action.upper(), idempotency_key=args.key or str(uuid.uuid4()))
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        except (OwnerTimeRejected, OSError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 3
    if args.action == "serve" and not os.environ.get("AUTOLOOP_OWNER_PASSWORD"):
        print("Set AUTOLOOP_OWNER_PASSWORD (12+ characters) before serving the owner UI", file=sys.stderr)
        return 2
    args.db.parent.mkdir(parents=True, exist_ok=True)
    url = sqlite_url(args.db)
    migrate(url)
    engine = create_database_engine(url)
    dispatch = Dispatcher(engine)
    try:
        if args.action == "init-db":
            result = {"status": "MIGRATED", "db": str(args.db)}
        elif args.action == "add-project":
            dispatch.add_project(project_id=args.id, name=args.name, repo_url=args.repo_url)
            result = {"created": args.id}
        elif args.action == "add-plan":
            dispatch.add_plan(plan_id=args.id, project_id=args.project, spec_hash=args.spec_hash)
            result = {"created": args.id}
        elif args.action == "add-task":
            instructions = args.instructions_file.read_text(encoding="utf-8") if args.instructions_file else args.title
            dispatch.add_task(task_id=args.id, plan_id=args.plan, title=args.title, acceptance_spec_hash=args.acceptance_hash, dependency_ids=args.depends_on, instructions=instructions)
            result = {"created": args.id}
        elif args.action == "claim":
            result = dispatch.claim_next(worker_id=args.worker, idempotency_key=args.key or str(uuid.uuid4()))
        elif args.action == "tasks":
            result = dispatch.list_tasks()
        elif args.action == "events":
            result = dispatch.events_for(args.task)
        elif args.action == "stop":
            result = dispatch.request_stop(task_id=args.task, idempotency_key=args.key or str(uuid.uuid4()))
        elif args.action == "resume":
            result = dispatch.resume_owner_stop(task_id=args.task, idempotency_key=args.key or str(uuid.uuid4()))
        elif args.action == "serve":
            import uvicorn
            # This entry point binds loopback HTTP only. Secure cookies are
            # rejected by browsers on non-TLS remote HTTP, so local HTTP uses
            # a host-only HttpOnly cookie. For a TLS deployment, instantiate
            # create_app(..., secure_cookie=True) behind a trusted proxy.
            app = create_app(engine, owner_password=os.environ["AUTOLOOP_OWNER_PASSWORD"], secure_cookie=False)
            # Deliberately loopback-only. Remote access is through an
            # authenticated private tunnel, never a public shell endpoint.
            uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False)
            return 0
        else:
            raise AssertionError("unreachable argparse action")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (DispatchRejected, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 3
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
