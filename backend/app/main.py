from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from collections import defaultdict, deque
from datetime import datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import AuthSession, BotUpdate, BusinessProfile, ChecklistItem, IdempotencyKey, Notification, SessionLocal, SupportProgram, User, ApplicationPlan, now
from .matching import MOSCOW, evaluate, sort_key
from .max_api import MaxAuthError, app_link, verify_init_data
from .schemas import DemoReminderIn, ItemCreate, ItemPatch, MaxAuthIn, PlanIn, PlanPatch, ProfileIn


settings.validate()
app = FastAPI(title="ДЕЛО API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST", "PUT", "PATCH"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
BUCKETS: dict[str, deque] = defaultdict(deque)


def error(status: int, code: str, message: str):
    raise HTTPException(status, {"code": code, "message": message})


@app.middleware("http")
async def request_guard(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    if request.method in {"POST", "PUT", "PATCH"} and len(await request.body()) > 65536:
        return JSONResponse(status_code=413, content={"error": {"code": "too_large", "message": "Запрос слишком большой", "field_errors": {}}, "request_id": request_id})
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": {**detail, "field_errors": detail.get("field_errors", {})}, "request_id": request.state.request_id})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    fields = {".".join(map(str, item["loc"])): item["msg"] for item in exc.errors()}
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Проверьте поля формы", "field_errors": fields}, "request_id": request.state.request_id})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Внутренняя ошибка сервера", "field_errors": {}}, "request_id": request.state.request_id})


def token_hash(token: str) -> str:
    return hmac.new(settings.session_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def limited(key: str, max_hits: int, seconds: int):
    bucket = BUCKETS[key]
    current = now().timestamp()
    while bucket and bucket[0] < current - seconds:
        bucket.popleft()
    if len(bucket) >= max_hits:
        error(429, "rate_limited", "Слишком много запросов. Повторите позже")
    bucket.append(current)


def get_db():
    with SessionLocal() as session:
        yield session


Db = Annotated[Session, Depends(get_db)]
bearer = HTTPBearer(auto_error=False)


def current_user(db: Db, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> User:
    if not credentials:
        error(401, "unauthorized", "Откройте приложение через MAX или войдите в деморежим")
    token = credentials.credentials
    if len(token) < 32:
        error(401, "unauthorized", "Сессия недействительна")
    row = db.get(AuthSession, token_hash(token))
    if not row or (row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at) <= now():
        error(401, "session_expired", "Сессия истекла. Откройте приложение повторно")
    user = db.get(User, row.user_id)
    if not user:
        error(401, "unauthorized", "Пользователь не найден")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def session_token(db: Session, user: User) -> dict:
    token = secrets.token_urlsafe(32)
    expires = now() + timedelta(hours=2)
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, expires_at=expires))
    db.commit()
    return {"token": token, "expires_at": expires.isoformat(), "mode": "demo" if user.max_user_id == "demo" else "max"}


def iso_utc(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.astimezone(timezone.utc).isoformat()


def profile_dict(row: BusinessProfile | None) -> dict | None:
    if not row:
        return None
    return {key: iso_utc(value) if isinstance(value, datetime) else value.isoformat() if isinstance(value, __import__("datetime").date) else value for key, value in vars(row).items() if key in {"business_name", "legal_form", "region_code", "industry_code", "employee_count", "registration_date", "purpose_code", "tax_debt", "revenue", "version", "updated_at"}}


def program_dict(row: SupportProgram, profile: dict | None, *, details: bool = False) -> dict:
    data = {
        "id": row.id, "title": row.title, "operator_name": row.operator_name,
        "purpose_code": row.purpose_code, "region_code": row.region_code,
        "benefit_type": row.benefit_type, "amount_text": row.amount_text,
        "deadline": row.deadline.isoformat() if row.deadline else None,
        "state": row.state, "description": row.description, "version": row.version,
        "provenance": row.provenance, "match": evaluate(row, profile, demo_rules=settings.seed_demo),
    }
    if details:
        data["rules"] = row.rules
        data["documents"] = row.document_template
    return data


def plan_dict(db: Session, row: ApplicationPlan) -> dict:
    items = list(db.scalars(select(ChecklistItem).where(ChecklistItem.plan_id == row.id).order_by(ChecklistItem.order)))
    done = sum(item.status == "done" for item in items)
    current_program = db.get(SupportProgram, row.program_id)
    return {
        "id": row.id, "program_id": row.program_id, "program_snapshot": row.program_snapshot,
        "due_at": iso_utc(row.due_at),
        "status": row.status, "version": row.version, "reminders_enabled": row.reminders_enabled,
        "program_changed": bool(current_program and current_program.version != row.program_snapshot.get("version")),
        "progress": round(done / len(items) * 100) if items else 0,
        "items": [{"id": item.id, "title": item.title, "kind": item.kind, "status": item.status, "order": item.order, "due_at": iso_utc(item.due_at) if item.due_at else None} for item in items],
    }


def due_check(program: SupportProgram, due_at: datetime):
    if due_at <= now():
        error(422, "invalid_due_at", "Дата подготовки должна быть в будущем")
    if program.deadline and due_at.astimezone(MOSCOW).date() > program.deadline:
        error(422, "after_deadline", "Дата подготовки позже срока программы")


def reminder_time(due_at: datetime, specified: datetime | None):
    chosen = specified or due_at - timedelta(days=1)
    if chosen <= now() or chosen >= due_at:
        error(422, "invalid_reminder", "Выберите будущее время напоминания до даты подготовки")
    return chosen.astimezone(timezone.utc)


def add_notification(db: Session, user: User, plan: ApplicationPlan | None, kind: str, message: str, when: datetime, dedupe: str):
    db.add(Notification(user_id=user.id, plan_id=plan.id if plan else None, type=kind, message=message, scheduled_at=when, dedupe_key=dedupe))


def own_plan(db: Session, user: User, plan_id: str) -> ApplicationPlan:
    row = db.get(ApplicationPlan, plan_id)
    if not row or row.user_id != user.id:
        error(404, "not_found", "План не найден")
    return row


def claim_version(db: Session, row: BusinessProfile | ApplicationPlan, expected: int) -> None:
    model = type(row)
    key = model.user_id == row.user_id if isinstance(row, BusinessProfile) else model.id == row.id
    result = db.execute(
        update(model).where(key, model.version == expected).values(version=model.version + 1, updated_at=now())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        error(409, "version_conflict", "Данные изменены на другом устройстве. Загрузите актуальную версию")
    db.refresh(row)


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready(db: Db):
    db.scalar(select(User).limit(1))
    return {"status": "ok"}


@app.post("/api/v1/auth/max")
def auth_max(payload: MaxAuthIn, request: Request, db: Db):
    limited("auth:" + (request.client.host if request.client else "unknown"), 20, 60)
    try:
        max_user = verify_init_data(payload.init_data, settings.max_token)
    except MaxAuthError:
        error(401, "invalid_init_data", "Не удалось подтвердить запуск через MAX")
    max_id = str(max_user["id"])
    user = db.scalar(select(User).where(User.max_user_id == max_id))
    if not user:
        user = User(max_user_id=max_id, display_name=(max_user.get("first_name") or "Пользователь")[:120])
        db.add(user)
        db.flush()
    return session_token(db, user)


@app.post("/api/v1/auth/demo")
def auth_demo(request: Request, db: Db):
    if settings.app_env == "production" or not settings.dev_auth_enabled:
        error(404, "not_found", "Деморежим выключен")
    limited("demo:" + (request.client.host if request.client else "unknown"), 120, 60)
    user = db.scalar(select(User).where(User.max_user_id == "demo"))
    if not user:
        user = User(max_user_id="demo", display_name="Демо", bot_started=True)
        db.add(user)
        db.flush()
    return session_token(db, user)


@app.get("/api/v1/me")
def me(user: CurrentUser):
    return {"id": user.id, "display_name": user.display_name, "mode": "demo" if user.max_user_id == "demo" else "max", "bot_started": user.bot_started}


@app.get("/api/v1/profile")
def get_profile(user: CurrentUser, db: Db):
    return profile_dict(db.get(BusinessProfile, user.id))


@app.put("/api/v1/profile")
def put_profile(payload: ProfileIn, user: CurrentUser, db: Db):
    row = db.get(BusinessProfile, user.id)
    values = payload.model_dump(exclude={"version"})
    if row:
        if payload.version != row.version:
            error(409, "version_conflict", "Профиль изменён на другом устройстве. Загрузите актуальные данные")
        claim_version(db, row, row.version)
        for key, value in values.items():
            setattr(row, key, value)
    else:
        if payload.version is not None:
            error(409, "version_conflict", "Профиль ещё не создан")
        row = BusinessProfile(user_id=user.id, **values)
        db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        error(409, "version_conflict", "Профиль создан на другом устройстве. Загрузите актуальные данные")
    return profile_dict(row)


@app.get("/api/v1/programs")
def programs(user: CurrentUser, db: Db, search: str = Query("", max_length=120), status: str | None = None, purpose: str | None = None):
    profile = profile_dict(db.get(BusinessProfile, user.id))
    rows = [program_dict(item, profile) for item in db.scalars(select(SupportProgram)) if settings.app_env != "production" or item.provenance.get("data_kind") != "synthetic"]
    rows = [item for item in rows if search.lower() in item["title"].lower()]
    if status:
        rows = [item for item in rows if item["match"]["status"] == status]
    if purpose:
        rows = [item for item in rows if item["purpose_code"] == purpose]
    return sorted(rows, key=lambda item: sort_key(item, profile.get("purpose_code") if profile else None))


@app.get("/api/v1/programs/{program_id}")
def program(program_id: str, user: CurrentUser, db: Db):
    row = db.get(SupportProgram, program_id)
    if not row or (settings.app_env == "production" and row.provenance.get("data_kind") == "synthetic"):
        error(404, "not_found", "Программа не найдена")
    return program_dict(row, profile_dict(db.get(BusinessProfile, user.id)), details=True)


@app.get("/api/v1/dashboard")
def dashboard(user: CurrentUser, db: Db):
    profile = profile_dict(db.get(BusinessProfile, user.id))
    if not profile:
        return {"profile": None, "recommendations": [], "active_plans": 0, "next_item": None}
    catalog = sorted([program_dict(item, profile) for item in db.scalars(select(SupportProgram)) if settings.app_env != "production" or item.provenance.get("data_kind") != "synthetic"], key=lambda item: sort_key(item, profile["purpose_code"]))
    active = list(db.scalars(select(ApplicationPlan).where(ApplicationPlan.user_id == user.id, ApplicationPlan.status == "active").order_by(ApplicationPlan.due_at)))
    next_item = None
    for plan in active:
        item = db.scalar(select(ChecklistItem).where(ChecklistItem.plan_id == plan.id, ChecklistItem.status == "todo").order_by(ChecklistItem.order))
        if item:
            next_item = {"plan_id": plan.id, "title": item.title, "due_at": iso_utc(plan.due_at)}
            break
    return {"profile": profile, "recommendations": [p for p in catalog if p["match"]["status"] in {"preliminary_match", "check_needed"}][:3], "active_plans": len(active), "next_item": next_item}


@app.post("/api/v1/plans", status_code=201)
def create_plan(payload: PlanIn, response: Response, user: CurrentUser, db: Db, idempotency_key: str | None = Header(None)):
    if not idempotency_key or len(idempotency_key) > 128:
        error(422, "idempotency_required", "Нужен заголовок Idempotency-Key")
    content_hash = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
    previous = db.get(IdempotencyKey, (user.id, idempotency_key))
    if previous:
        if previous.payload_hash != content_hash:
            error(409, "idempotency_conflict", "Этот ключ уже использован для другого запроса")
        response.status_code = 200
        return plan_dict(db, own_plan(db, user, previous.plan_id))
    profile = profile_dict(db.get(BusinessProfile, user.id))
    if not profile:
        error(422, "profile_required", "Сначала заполните профиль")
    program = db.get(SupportProgram, payload.program_id)
    if not program:
        error(404, "not_found", "Программа не найдена")
    snapshot = program_dict(program, profile, details=True)
    if snapshot["match"]["status"] not in {"preliminary_match", "check_needed"}:
        error(422, "plan_not_allowed", "Новый план для этой программы недоступен")
    due_check(program, payload.due_at)
    if payload.reminders_enabled and not user.bot_started:
        error(422, "bot_not_started", "Сначала запустите бота MAX")
    remind_at = reminder_time(payload.due_at, payload.reminder_at) if payload.reminders_enabled else None
    plan = ApplicationPlan(user_id=user.id, program_id=program.id, program_snapshot=snapshot, due_at=payload.due_at.astimezone(timezone.utc), reminders_enabled=payload.reminders_enabled)
    try:
        db.add(plan)
        db.flush()
        docs = [{"title": title, "kind": "document"} for title in program.document_template]
        clarifications = [{"title": "Уточнить: " + result["explanation"], "kind": "clarification"} for result in snapshot["match"]["rules"] if result["required"] and result["outcome"] == "unknown"]
        for order, item in enumerate(docs + clarifications):
            db.add(ChecklistItem(plan_id=plan.id, title=item["title"], kind=item["kind"], order=order))
        if user.bot_started:
            add_notification(db, user, plan, "confirmation", f"ДЕЛО: план «{program.title}» создан.", now(), f"plan:{plan.id}:created")
        if remind_at:
            add_notification(db, user, plan, "reminder", f"ДЕЛО: скоро срок подготовки плана «{program.title}».", remind_at, f"plan:{plan.id}:reminder:1")
        db.add(IdempotencyKey(user_id=user.id, key=idempotency_key, payload_hash=content_hash, plan_id=plan.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        error(409, "active_plan_exists", "Активный план по этой программе уже существует")
    return plan_dict(db, plan)


@app.get("/api/v1/plans")
def plans(user: CurrentUser, db: Db):
    return [plan_dict(db, row) for row in db.scalars(select(ApplicationPlan).where(ApplicationPlan.user_id == user.id).order_by(ApplicationPlan.created_at.desc()))]


@app.get("/api/v1/plans/{plan_id}")
def get_plan(plan_id: str, user: CurrentUser, db: Db):
    return plan_dict(db, own_plan(db, user, plan_id))


@app.patch("/api/v1/plans/{plan_id}")
def patch_plan(plan_id: str, payload: PlanPatch, user: CurrentUser, db: Db):
    plan = own_plan(db, user, plan_id)
    if payload.version != plan.version:
        error(409, "version_conflict", "План изменён на другом устройстве. Загрузите актуальные данные")
    if plan.status != "active":
        error(409, "plan_inactive", "Этот план уже завершён или отменён")
    claim_version(db, plan, payload.version)
    program = db.get(SupportProgram, plan.program_id)
    new_due = payload.due_at or plan.due_at.replace(tzinfo=timezone.utc)
    if payload.due_at:
        due_check(program, new_due)
        plan.due_at = new_due.astimezone(timezone.utc)
    if payload.reminders_enabled is not None:
        if payload.reminders_enabled and not user.bot_started:
            error(422, "bot_not_started", "Сначала запустите бота MAX")
        plan.reminders_enabled = payload.reminders_enabled
    if payload.status:
        plan.status = payload.status
    if payload.due_at or payload.reminders_enabled is not None or payload.reminder_at or plan.status != "active":
        for n in db.scalars(select(Notification).where(Notification.plan_id == plan.id, Notification.type.in_(["reminder", "demo_reminder"]), Notification.status == "pending")):
            n.status = "cancelled"
        if plan.status == "active" and plan.reminders_enabled:
            when = reminder_time(new_due, payload.reminder_at)
            add_notification(db, user, plan, "reminder", f"ДЕЛО: скоро срок подготовки плана «{program.title}».", when, f"plan:{plan.id}:reminder:{plan.version}")
    db.commit()
    return plan_dict(db, plan)


@app.patch("/api/v1/plans/{plan_id}/items/{item_id}")
def patch_item(plan_id: str, item_id: str, payload: ItemPatch, user: CurrentUser, db: Db):
    plan = own_plan(db, user, plan_id)
    if plan.status != "active":
        error(409, "plan_inactive", "План неактивен")
    if payload.version != plan.version:
        error(409, "version_conflict", "План изменён на другом устройстве. Загрузите актуальные данные")
    item = db.get(ChecklistItem, item_id)
    if not item or item.plan_id != plan.id:
        error(404, "not_found", "Пункт не найден")
    claim_version(db, plan, payload.version)
    item.status = payload.status
    db.commit()
    return plan_dict(db, plan)


@app.post("/api/v1/plans/{plan_id}/items", status_code=201)
def add_item(plan_id: str, payload: ItemCreate, user: CurrentUser, db: Db):
    plan = own_plan(db, user, plan_id)
    if plan.status != "active":
        error(409, "plan_inactive", "План неактивен")
    if payload.version != plan.version:
        error(409, "version_conflict", "План изменён на другом устройстве. Загрузите актуальные данные")
    if not payload.title.strip():
        error(422, "invalid_title", "Введите название действия")
    items = list(db.scalars(select(ChecklistItem).where(ChecklistItem.plan_id == plan.id)))
    if len(items) >= 100:
        error(422, "item_limit", "В плане уже 100 пунктов")
    claim_version(db, plan, payload.version)
    db.add(ChecklistItem(plan_id=plan.id, title=payload.title.strip(), kind="action", order=max((item.order for item in items), default=-1) + 1))
    db.commit()
    return plan_dict(db, plan)


@app.get("/api/v1/plans/{plan_id}/notifications")
def notifications(plan_id: str, user: CurrentUser, db: Db):
    own_plan(db, user, plan_id)
    return [{"id": n.id, "type": n.type, "scheduled_at": iso_utc(n.scheduled_at), "status": n.status, "attempts": n.attempts} for n in db.scalars(select(Notification).where(Notification.plan_id == plan_id).order_by(Notification.scheduled_at))]


@app.post("/api/v1/demo/reminder", status_code=201)
def demo_reminder(payload: DemoReminderIn, request: Request, user: CurrentUser, db: Db):
    if not settings.reminder_demo_enabled or not settings.dev_auth_enabled or settings.app_env == "production":
        error(404, "not_found", "Тестовые напоминания выключены")
    limited("reminder:" + user.id, 3, 3600)
    plan = own_plan(db, user, payload.plan_id)
    if plan.status != "active":
        error(409, "plan_inactive", "План неактивен")
    when = now() + timedelta(seconds=60)
    add_notification(db, user, plan, "demo_reminder", "ДЕЛО: тестовое напоминание о плане.", when, f"plan:{plan.id}:demo:{uuid.uuid4()}")
    db.commit()
    return {"status": "pending", "scheduled_at": when.isoformat()}


@app.post("/api/v1/integrations/max/webhook")
async def max_webhook(request: Request, db: Db, x_max_bot_api_secret: str | None = Header(None)):
    if not settings.max_webhook_secret or not x_max_bot_api_secret or not hmac.compare_digest(x_max_bot_api_secret, settings.max_webhook_secret):
        error(401, "invalid_webhook", "Webhook не подтверждён")
    raw = await request.body()
    try:
        update = json.loads(raw)
    except ValueError:
        error(422, "invalid_update", "Некорректное событие")
    event_key = hashlib.sha256(raw).hexdigest()
    if db.get(BotUpdate, event_key):
        return {"accepted": True}
    kind = update.get("update_type")
    if kind == "bot_started":
        person = update.get("user") or {}
    elif kind == "message_created":
        person = (update.get("message") or {}).get("sender") or {}
    else:
        person = {}
    max_id = person.get("user_id")
    if kind in {"bot_started", "message_created"} and isinstance(max_id, int) and max_id > 0:
        user = db.scalar(select(User).where(User.max_user_id == str(max_id)))
        if not user:
            user = User(max_user_id=str(max_id), display_name=(person.get("name") or "Пользователь")[:120])
            db.add(user)
            db.flush()
        user.bot_started = True
        message = ((update.get("message") or {}).get("body") or {}).get("text", "").strip().lower()
        if kind == "bot_started" or message in {"/start", "помощь", "/help", "найти поддержку", "мои планы"}:
            if message == "мои планы":
                body = "Откройте свои планы в ДЕЛО."
                link = app_link("plans")
            elif message in {"помощь", "/help"}:
                body = "ДЕЛО поможет найти учебные меры поддержки и составить план. Откройте мини-приложение через кнопку бота."
                link = app_link()
            else:
                body = "ДЕЛО подберёт меры поддержки и поможет составить план. Нажмите «Открыть» в боте."
                link = app_link("support")
            if link:
                body += f"\n{link}"
            add_notification(db, user, None, "bot_reply", body, now(), f"bot:{event_key}")
    db.add(BotUpdate(event_key=event_key))
    db.commit()
    return {"accepted": True}
