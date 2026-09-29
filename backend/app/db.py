from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings


def now() -> datetime:
    return datetime.now(timezone.utc)


engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    max_user_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(120), default="Пользователь")
    bot_started: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BusinessProfile(Base):
    __tablename__ = "business_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    business_name: Mapped[str] = mapped_column(String(120))
    legal_form: Mapped[str] = mapped_column(String(3))
    region_code: Mapped[str] = mapped_column(String(30))
    industry_code: Mapped[str] = mapped_column(String(60))
    employee_count: Mapped[int] = mapped_column(Integer)
    registration_date: Mapped[date] = mapped_column(Date)
    purpose_code: Mapped[str] = mapped_column(String(40))
    tax_debt: Mapped[str] = mapped_column(String(7), default="unknown")
    revenue: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class SupportProgram(Base):
    __tablename__ = "support_programs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    operator_name: Mapped[str] = mapped_column(String(160))
    purpose_code: Mapped[str] = mapped_column(String(40))
    region_code: Mapped[str] = mapped_column(String(30))
    benefit_type: Mapped[str] = mapped_column(String(80))
    amount_text: Mapped[str | None] = mapped_column(String(160))
    deadline: Mapped[date | None] = mapped_column(Date)
    state: Mapped[str] = mapped_column(String(16), default="open")
    description: Mapped[str] = mapped_column(Text)
    rules: Mapped[list] = mapped_column(JSON)
    document_template: Mapped[list] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ApplicationPlan(Base):
    __tablename__ = "application_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    program_id: Mapped[str] = mapped_column(ForeignKey("support_programs.id"))
    program_snapshot: Mapped[dict] = mapped_column(JSON)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("uq_active_user_program", "user_id", "program_id", unique=True, postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'")),)


class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id: Mapped[str] = mapped_column(ForeignKey("application_plans.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(8), default="todo")
    order: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("application_plans.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(String(4000))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    external_message_id: Mapped[str | None] = mapped_column(String(160))
    error_code: Mapped[str | None] = mapped_column(String(80))


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    plan_id: Mapped[str] = mapped_column(ForeignKey("application_plans.id"))


class BotUpdate(Base):
    __tablename__ = "bot_updates"
    event_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    status: Mapped[str] = mapped_column(String(16), default="processed")
