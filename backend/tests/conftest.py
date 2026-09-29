import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

database_path = Path(tempfile.gettempdir()) / "delo_backend_tests.sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
os.environ["APP_ENV"] = "development"
os.environ["DEV_AUTH_ENABLED"] = "true"
os.environ["SEED_DEMO"] = "true"
os.environ["REMINDER_DEMO_ENABLED"] = "true"
os.environ["USE_MOCK_MAX"] = "true"

from sqlalchemy import delete, select

from app.db import Base, BusinessProfile, SessionLocal, User, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_demo  # noqa: E402


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed_demo()
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.max_user_id == "demo"))
        db.execute(delete(BusinessProfile).where(BusinessProfile.user_id == user.id))
    with TestClient(app) as result:
        yield result


@pytest.fixture
def auth(client):
    response = client.post("/api/v1/auth/demo")
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}
