"""Portable SQLAlchemy schema; SQLite/WAL initially, PostgreSQL later."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_url: Mapped[str | None] = mapped_column(Text)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    instructions_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="READY", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acceptance_spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dependency_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    block_reason: Mapped[str | None] = mapped_column(String(100))
    repair_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_attempt_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    depends_on_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(String(120), nullable=False)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RunnerSession(Base):
    __tablename__ = "runner_sessions"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id"), nullable=False)
    external_session_id: Mapped[str | None] = mapped_column(String(255))
    pid: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class Lease(Base):
    __tablename__ = "leases"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    worker_id: Mapped[str | None] = mapped_column(String(120))
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = "events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(24))
    to_state: Mapped[str] = mapped_column(String(24), nullable=False)
    task_version: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_id: Mapped[str | None] = mapped_column(String(120))
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(120), nullable=False)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CommandReceipt(Base):
    __tablename__ = "command_receipts"
    request_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    __table_args__ = (UniqueConstraint("task_id", "idempotency_key", name="uq_task_command_key"),)


class Evidence(Base):
    __tablename__ = "evidence"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    base_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    tested_tree_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    suite_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    acceptance_spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ci_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    qa_verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    invalidated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class QAVerdict(Base):
    __tablename__ = "qa_verdicts"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    evidence_key: Mapped[str] = mapped_column(ForeignKey("evidence.key"), nullable=False)
    verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    qa_session_id: Mapped[str] = mapped_column(String(120), nullable=False)
    failure_fingerprint: Mapped[str | None] = mapped_column(String(64))


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(120), nullable=False)
    granted_by: Mapped[str] = mapped_column(String(120), nullable=False)
    evidence_key: Mapped[str | None] = mapped_column(String(64))


class UsageSample(Base):
    __tablename__ = "usage_samples"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id"), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    context_percent: Mapped[float | None]
    subscription_remaining: Mapped[int | None] = mapped_column(Integer)

