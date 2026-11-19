"""Owner-only mobile API. No shell endpoint and no bearer token in frontend storage."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import secrets
import time

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from autoloop.context import ContextTracker
from autoloop.dispatcher import DispatchRejected, Dispatcher


ROOT = Path(__file__).resolve().parents[2]
COOKIE_NAME = "autoloop_owner_session"
SESSION_SECONDS = 3600


class LoginBody(BaseModel):
    password: str


class CommandBody(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=200)


def create_app(engine: Engine, *, owner_password: str, secure_cookie: bool = True) -> FastAPI:
    if not owner_password or len(owner_password) < 12:
        raise ValueError("AUTOLOOP_UI_PASSWORD_REQUIRED_MIN_12")
    if not secure_cookie and not str(engine.url).startswith("sqlite:///"):
        raise ValueError("INSECURE_SESSION_ONLY_ALLOWED_FOR_LOCAL_TEST")
    dispatcher = Dispatcher(engine)
    context_tracker = ContextTracker(engine)
    app = FastAPI(title="autoLoop owner API", version="0.3.0-dev", docs_url=None, redoc_url=None, openapi_url=None)
    sessions: dict[str, tuple[float, str]] = {}
    login_failures: dict[str, list[float]] = defaultdict(list)

    @app.exception_handler(DispatchRejected)
    def rejected(_request: Request, exc: DispatchRejected) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": str(exc)})

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'"
        return response

    def require_owner(request: Request) -> str:
        session = request.cookies.get(COOKIE_NAME, "")
        record = sessions.get(session)
        if not record or record[0] <= time.monotonic():
            raise HTTPException(status_code=401, detail="OWNER_LOGIN_REQUIRED")
        return session

    def require_write(request: Request, session: str = Depends(require_owner)) -> str:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(supplied, sessions[session][1]):
            raise HTTPException(status_code=403, detail="CSRF_REQUIRED")
        origin = request.headers.get("Origin")
        expected = str(request.base_url).rstrip("/")
        if origin and origin.rstrip("/") != expected:
            raise HTTPException(status_code=403, detail="ORIGIN_MISMATCH")
        return session

    @app.get("/health")
    def health() -> dict:
        with Session(engine) as session:
            session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.post("/api/login")
    def login(body: LoginBody, request: Request, response: Response) -> dict:
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        failures = [stamp for stamp in login_failures[ip] if now - stamp < 60]
        login_failures[ip] = failures
        if len(failures) >= 5:
            raise HTTPException(status_code=429, detail="TRY_LATER")
        if not secrets.compare_digest(body.password, owner_password):
            login_failures[ip].append(now)
            raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
        login_failures.pop(ip, None)
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        sessions[session_id] = (now + SESSION_SECONDS, csrf_token)
        response.set_cookie(COOKIE_NAME, session_id, max_age=SESSION_SECONDS, httponly=True, secure=secure_cookie, samesite="strict", path="/")
        return {"status": "AUTHENTICATED", "expires_in_seconds": SESSION_SECONDS}

    @app.get("/api/session")
    def session_info(session: str = Depends(require_owner)) -> dict:
        # CSRF is ephemeral and held in JS memory only, never localStorage.
        return {"authenticated": True, "csrf_token": sessions[session][1]}

    @app.post("/api/logout")
    def logout(response: Response, session: str = Depends(require_write)) -> dict:
        sessions.pop(session, None)
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"status": "LOGGED_OUT"}

    @app.get("/api/tasks")
    def tasks(_session: str = Depends(require_owner)) -> list[dict]:
        return dispatcher.list_tasks()

    @app.get("/api/tasks/{task_id}/events")
    def task_events(task_id: str, _session: str = Depends(require_owner)) -> list[dict]:
        return dispatcher.events_for(task_id)

    @app.get("/api/attempts/{attempt_id}/usage")
    def attempt_usage(attempt_id: str, _session: str = Depends(require_owner)) -> dict:
        return context_tracker.observed_usage(attempt_id)

    @app.post("/api/tasks/{task_id}/stop")
    def stop_task(task_id: str, body: CommandBody, _session: str = Depends(require_write)) -> dict:
        return dispatcher.request_stop(task_id=task_id, idempotency_key=body.idempotency_key)

    @app.post("/api/tasks/{task_id}/resume")
    def resume_task(task_id: str, body: CommandBody, _session: str = Depends(require_write)) -> dict:
        return dispatcher.resume_owner_stop(task_id=task_id, idempotency_key=body.idempotency_key)

    app.mount("/ui", StaticFiles(directory=ROOT / "web", html=True), name="ui")
    return app
