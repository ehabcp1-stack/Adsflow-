from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="adflow-test-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TMP / 'test.db'}")
os.environ.setdefault("STORAGE_LOCAL_DIR", str(TMP / "storage"))
os.environ.setdefault("ENABLE_LOCAL_RENDER", "false")  # keep tests fast, no ffmpeg
os.environ.setdefault("FORCE_MOCK_PROVIDERS", "true")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import BrandKit, Organization, Project, User  # noqa: E402
from app.services import production as _production  # noqa: E402,F401  (registers job handlers)


@pytest.fixture(scope="session", autouse=True)
def _database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def org(db) -> Organization:
    organization = db.query(Organization).first()
    if not organization:
        organization = Organization(name="TADAFQ", name_ar="تدفق")
        db.add(organization)
        db.commit()
    return organization


@pytest.fixture
def user(db, org) -> User:
    existing = db.query(User).filter(User.email == "demo@tadafq.com").first()
    if existing:
        return existing
    account = User(
        email="demo@tadafq.com",
        full_name="Demo",
        hashed_password=hash_password("demo1234"),
        organization_id=org.id,
    )
    db.add(account)
    db.commit()
    return account


@pytest.fixture
def brand(db, org) -> BrandKit:
    kit = db.query(BrandKit).filter(BrandKit.organization_id == org.id).first()
    if not kit:
        kit = BrandKit(organization_id=org.id, name="Demo Brand", phone="07700000000", is_default=True)
        db.add(kit)
        db.commit()
    return kit


@pytest.fixture
def make_project(db, org, user, brand):
    def _make(**overrides) -> Project:
        data = {
            "organization_id": org.id,
            "created_by_id": user.id,
            "brand_kit_id": brand.id,
            "name": "مشروع اختبار",
            "category": "real_estate",
            "goal": "leads",
            "duration_sec": 15,
            "language": "iraqi_arabic",
            "dialect": "iraqi_professional",
            "cta": "اتصل بينا",
            "key_information": "شقق ١٥٠ متر\nأقساط مريحة",
            "budget_limit_usd": 12.0,
        }
        data.update(overrides)
        project = Project(**data)
        db.add(project)
        db.commit()
        return project

    return _make


@pytest.fixture
def client(user) -> TestClient:
    return TestClient(app)


#: Stage name -> (endpoint that starts it, endpoint that reports on it).
_STAGES = {
    "analysis": ("/analysis/run", "/analysis"),
    "concepts": ("/concepts/generate", "/concepts"),
    "script": ("/script/generate", "/script"),
    "storyboard": ("/storyboard/generate", "/storyboard"),
}


@pytest.fixture
def stage(client):
    """Start a writing stage and poll until it lands, the way a browser does.

    These four endpoints used to do the work inline, so every test could
    assume the response already carried the result. They now queue a job —
    because against a real LLM the inline call outlived the HTTP connection
    and the work was lost — so the client polls. Tests poll too: a helper that
    reached into the job system instead would stop exercising the path the
    product actually uses.
    """
    import time

    def _run(pid: str, name: str, *, regenerate: bool = False, timeout: float = 30.0) -> dict:
        start, report = _STAGES[name]
        started = client.post(f"/api/v1/projects/{pid}{start}", params={"regenerate": regenerate})
        assert started.status_code == 200, started.text
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            payload = client.get(f"/api/v1/projects/{pid}{report}").json()
            job = payload.get("job") or {}
            if job.get("status") == "completed":
                return payload
            assert job.get("status") != "failed", f"{name} job failed: {job.get('error_message')}"
            time.sleep(0.05)
        raise AssertionError(f"{name} did not finish within {timeout}s")

    return _run
