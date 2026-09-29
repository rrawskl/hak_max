import hashlib
import hmac
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.db import ApplicationPlan, AuthSession, BotUpdate, BusinessProfile, Notification, SessionLocal, SupportProgram, User
from app.max_api import MaxAuthError, PermanentMaxError, TemporaryMaxError, UncertainMaxError, verify_init_data
from app.main import token_hash
from app.seed import SeedProgram
from app.seed import seed_demo
from app.worker import process_due


def profile():
    return {
        "business_name": "Тестовая компания", "legal_form": "ip", "region_code": "spb",
        "industry_code": "services", "employee_count": 3,
        "registration_date": (date.today() - timedelta(days=600)).isoformat(),
        "purpose_code": "equipment", "tax_debt": "unknown", "revenue": None,
    }


def test_auth_signature_and_expiry():
    issued = int(datetime.now(timezone.utc).timestamp())
    fields = {"auth_date": str(issued), "user": json.dumps({"id": 123, "first_name": "Анна"}, separators=(",", ":"))}
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    canonical = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
    raw = urlencode(fields)
    assert verify_init_data(raw, "test-token", now_seconds=issued)["id"] == 123
    try:
        verify_init_data(raw.replace("123", "124"), "test-token", now_seconds=issued)
        assert False
    except MaxAuthError:
        pass
    try:
        verify_init_data(raw, "test-token", now_seconds=issued + 3601)
        assert False
    except MaxAuthError:
        pass


def test_profile_catalogue_and_plan_flow(client, auth):
    assert client.get("/api/v1/profile").status_code == 401
    saved = client.put("/api/v1/profile", headers=auth, json=profile())
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    conflict = client.put("/api/v1/profile", headers=auth, json=profile())
    assert conflict.status_code == 409
    catalog = client.get("/api/v1/programs", headers=auth).json()
    assert len(catalog) == 8
    equipment = next(item for item in catalog if item["id"] == "equipment")
    assert equipment["match"]["status"] == "check_needed"
    assert equipment["provenance"]["source_url"] is None
    due = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
    body = {"program_id": "equipment", "due_at": due, "reminders_enabled": True}
    headers = {**auth, "Idempotency-Key": "same-key"}
    created = client.post("/api/v1/plans", headers=headers, json=body)
    assert created.status_code == 201, created.text
    plan = created.json()
    assert any(item["kind"] == "clarification" for item in plan["items"])
    repeated = client.post("/api/v1/plans", headers=headers, json=body)
    assert repeated.status_code == 200
    assert repeated.json()["id"] == plan["id"]
    assert client.post("/api/v1/plans", headers=headers, json={**body, "reminders_enabled": False}).status_code == 409
    assert client.post("/api/v1/plans", headers={**auth, "Idempotency-Key": "new-key"}, json=body).status_code == 409
    item = plan["items"][0]
    changed = client.patch(f"/api/v1/plans/{plan['id']}/items/{item['id']}", headers=auth, json={"version": 1, "status": "done"})
    assert changed.status_code == 200
    assert changed.json()["version"] == 2
    assert changed.json()["progress"] > 0
    assert client.patch(f"/api/v1/plans/{plan['id']}/items/{item['id']}", headers=auth, json={"version": 1, "status": "todo"}).status_code == 409
    assert process_due() >= 1
    notifications = client.get(f"/api/v1/plans/{plan['id']}/notifications", headers=auth).json()
    assert any(n["status"] == "simulated" for n in notifications)
    finished = client.patch(f"/api/v1/plans/{plan['id']}", headers=auth, json={"version": 2, "status": "completed"})
    assert finished.status_code == 200
    assert any(n["status"] == "cancelled" for n in client.get(f"/api/v1/plans/{plan['id']}/notifications", headers=auth).json())


def test_isolation_and_demo_reminder(client, auth):
    client.put("/api/v1/profile", headers=auth, json=profile())
    due = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    plan = client.post("/api/v1/plans", headers={**auth, "Idempotency-Key": "one"}, json={"program_id": "equipment", "due_at": due}).json()
    with SessionLocal.begin() as db:
        other = User(max_user_id="other", display_name="Другой", bot_started=True)
        db.add(other)
        db.flush()
        token = "o" * 44
        db.add(AuthSession(token_hash=token_hash(token), user_id=other.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    other_auth = {"Authorization": f"Bearer {token}"}
    assert client.get(f"/api/v1/plans/{plan['id']}", headers=other_auth).status_code == 404
    assert client.get(f"/api/v1/plans/{plan['id']}/notifications", headers=other_auth).status_code == 404
    test = client.post("/api/v1/demo/reminder", headers=auth, json={"plan_id": plan["id"]})
    assert test.status_code == 201
    assert test.json()["status"] == "pending"
    assert client.post("/api/v1/demo/reminder", headers=other_auth, json={"plan_id": plan["id"]}).status_code == 404


def test_closed_program_and_invalid_date_leave_no_plan(client, auth):
    client.put("/api/v1/profile", headers=auth, json=profile())
    due = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    assert client.post("/api/v1/plans", headers={**auth, "Idempotency-Key": "closed"}, json={"program_id": "closed-example", "due_at": due}).status_code == 422
    too_late = (datetime.now(timezone.utc) + timedelta(days=200)).isoformat()
    assert client.post("/api/v1/plans", headers={**auth, "Idempotency-Key": "late"}, json={"program_id": "equipment", "due_at": too_late}).status_code == 422
    with SessionLocal() as db:
        assert db.scalars(select(ApplicationPlan)).all() == []
        assert db.scalars(select(Notification)).all() == []


def test_webhook_secret_dedupe_and_started_user(client, monkeypatch):
    from dataclasses import replace
    from importlib import import_module
    main = import_module("app.main")
    monkeypatch.setattr(main, "settings", replace(main.settings, max_webhook_secret="test_secret"))
    event = {"update_type": "bot_started", "timestamp": 1, "chat_id": 123, "user": {"user_id": 456, "name": "Иван"}}
    url = "/api/v1/integrations/max/webhook"
    assert client.post(url, json=event).status_code == 401
    for _ in range(2):
        assert client.post(url, headers={"X-Max-Bot-Api-Secret": "test_secret"}, json=event).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.max_user_id == "456")).bot_started
        assert len(db.scalars(select(BotUpdate)).all()) == 1
        assert len(db.scalars(select(Notification)).all()) == 1


def test_worker_temporary_and_uncertain(client, monkeypatch):
    from app import worker
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.max_user_id == "demo"))
        row = Notification(user_id=user.id, type="bot_reply", message="Тест", scheduled_at=datetime.now(timezone.utc), dedupe_key="retry-test")
        db.add(row)
        db.flush()
        notification_id = row.id
    def temporary(*_args, **_kwargs):
        raise TemporaryMaxError()
    monkeypatch.setattr(worker, "send_message", temporary)
    assert worker.process_due() == 1
    with SessionLocal.begin() as db:
        row = db.get(Notification, notification_id)
        assert row.status == "pending" and row.attempts == 1
        row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    def uncertain(*_args, **_kwargs):
        raise UncertainMaxError()
    monkeypatch.setattr(worker, "send_message", uncertain)
    assert worker.process_due() == 1
    with SessionLocal() as db:
        assert db.get(Notification, notification_id).status == "uncertain"


def test_production_rejects_demo_auth():
    try:
        Settings(app_env="production", dev_auth_enabled=True).validate()
        assert False
    except RuntimeError:
        pass


def test_real_max_adapter_contract(monkeypatch):
    from app import max_api
    monkeypatch.setattr(max_api, "settings", replace(max_api.settings, max_token="test-token", max_bot_name="DeloBot", use_mock_max=False))
    calls = []
    def accepted(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"message": {"body": {"mid": "m1"}}})
    monkeypatch.setattr(max_api.httpx, "post", accepted)
    assert max_api.send_message("123", "План", plan_id="12345678-1234-1234-1234-123456789abc") == ("sent", "m1")
    assert calls[0][1]["headers"]["Authorization"] == "test-token"
    assert "startapp=plan_12345678_1234_1234_1234_123456789abc" in calls[0][1]["json"]["text"]
    monkeypatch.setattr(max_api.httpx, "post", lambda *_args, **_kwargs: httpx.Response(429))
    with pytest.raises(TemporaryMaxError):
        max_api.send_message("123", "План")
    monkeypatch.setattr(max_api.httpx, "post", lambda *_args, **_kwargs: httpx.Response(403))
    with pytest.raises(PermanentMaxError):
        max_api.send_message("123", "План")
    def timeout(*_args, **_kwargs):
        raise httpx.TimeoutException("timeout")
    monkeypatch.setattr(max_api.httpx, "post", timeout)
    with pytest.raises(UncertainMaxError):
        max_api.send_message("123", "План")


def test_empty_checklist_can_gain_action(client, auth):
    client.put("/api/v1/profile", headers=auth, json=profile())
    with SessionLocal.begin() as db:
        db.get(SupportProgram, "consulting").document_template = []
    due = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    result = client.post("/api/v1/plans", headers={**auth, "Idempotency-Key": "empty-list"}, json={"program_id": "consulting", "due_at": due})
    assert result.status_code == 201
    plan = result.json()
    assert plan["progress"] == 0 and plan["items"] == []
    created = client.post(f"/api/v1/plans/{plan['id']}/items", headers=auth, json={"version": plan["version"], "title": "Позвонить оператору"})
    assert created.status_code == 201
    assert created.json()["items"][0]["title"] == "Позвонить оператору"


def test_seed_rejects_bad_rule_before_import():
    from pathlib import Path
    rows = json.loads((Path(__file__).resolve().parents[2] / "data" / "programs.json").read_text(encoding="utf-8"))
    rows[0]["rules"][0]["operator"] = "not_supported"
    with pytest.raises(ValueError, match="Unsupported rule operator"):
        [SeedProgram.model_validate(item) for item in rows]


def test_seed_creates_demo_profile(client):
    assert seed_demo() == 8
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.max_user_id == "demo"))
        profile = db.get(BusinessProfile, user.id)
        assert profile.business_name == "Мастерская ДЕЛО"
        assert profile.tax_debt == "unknown"
