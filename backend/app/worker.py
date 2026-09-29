from __future__ import annotations

import time
from datetime import timedelta, timezone

from sqlalchemy import or_, select

from .config import settings
from .db import ApplicationPlan, AuthSession, BotUpdate, Notification, SessionLocal, User, now
from .max_api import PermanentMaxError, TemporaryMaxError, UncertainMaxError, send_message


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def process_due(limit: int = 20) -> int:
    current = now()
    claimed = []
    with SessionLocal.begin() as session:
        session.query(AuthSession).filter(AuthSession.expires_at < current).delete(synchronize_session=False)
        session.query(BotUpdate).filter(BotUpdate.received_at < current - timedelta(days=30)).delete(synchronize_session=False)
        query = (
            select(Notification)
            .where(
                or_(Notification.status == "pending", (Notification.status == "processing") & (Notification.lease_until < current)),
                Notification.scheduled_at <= current,
                or_(Notification.next_attempt_at.is_(None), Notification.next_attempt_at <= current),
            )
            .order_by(Notification.scheduled_at, Notification.id)
            .limit(limit)
        )
        if session.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        for row in session.scalars(query):
            row.status = "processing"
            row.lease_until = current + timedelta(seconds=45)
            row.attempts += 1
            claimed.append(row.id)
    for notification_id in claimed:
        with SessionLocal() as session:
            row = session.get(Notification, notification_id)
            user = session.get(User, row.user_id)
            plan = session.get(ApplicationPlan, row.plan_id) if row.plan_id else None
            if row.type in {"reminder", "demo_reminder"} and (not plan or plan.status != "active" or not plan.reminders_enabled and row.type == "reminder"):
                status, message_id, error = "cancelled", None, None
            elif not user or not user.bot_started or not user.max_user_id:
                status, message_id, error = "failed", None, "bot_not_started"
            else:
                try:
                    status, message_id = send_message(user.max_user_id, row.message, plan_id=row.plan_id)
                    error = None
                except UncertainMaxError:
                    status, message_id, error = "uncertain", None, "timeout"
                except TemporaryMaxError:
                    status, message_id, error = ("failed" if row.attempts >= 5 else "pending"), None, "temporary"
                except PermanentMaxError:
                    status, message_id, error = "failed", None, "permanent"
            row.status = status
            row.external_message_id = message_id
            row.error_code = error
            row.lease_until = None
            row.next_attempt_at = now() + timedelta(seconds=min(60 * 2 ** row.attempts, 3600)) if status == "pending" else None
            session.commit()
    return len(claimed)


if __name__ == "__main__":
    settings.validate()
    while True:
        process_due()
        time.sleep(2)
