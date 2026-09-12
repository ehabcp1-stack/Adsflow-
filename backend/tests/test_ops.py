"""Operational safety: logging redaction, webhooks, cancellation, readiness.

These are the behaviours that decide whether the system is safe to run in
production rather than whether it produces a nice ad.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.core import logging as adflow_logging
from app.core.config import settings
from app.core.enums import JobStatus, JobType

API = settings.API_PREFIX


# --------------------------------------------------------------------------
# Log redaction
# --------------------------------------------------------------------------
def test_configured_secrets_never_survive_redaction(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-supersecretvalue12345")
    text = "calling provider with key sk-supersecretvalue12345 ok"
    redacted = adflow_logging.redact(text)
    assert "sk-supersecretvalue12345" not in redacted
    assert adflow_logging.REDACTED in redacted


@pytest.mark.parametrize(
    "line",
    [
        "Authorization: Bearer abcdef123456789",
        'api_key="abcdef123456789"',
        "https://api.example.com/v1/go?api_key=abcdef123456789&x=1",
        "token=abcdef123456789",
        "password: hunter2hunter2",
    ],
)
def test_credential_shaped_text_is_redacted(line):
    redacted = adflow_logging.redact(line)
    assert "abcdef123456789" not in redacted
    assert "hunter2hunter2" not in redacted


def test_json_formatter_redacts_and_carries_context():
    import logging as std_logging

    formatter = adflow_logging.JsonFormatter()
    with adflow_logging.LogContext(request_id="req-1", job_id="job-1", project_id="proj-1"):
        record = std_logging.LogRecord(
            "adflow.test", std_logging.INFO, __file__, 1,
            "calling with api_key=abcdef123456789", None, None,
        )
        payload = json.loads(formatter.format(record))
    assert payload["request_id"] == "req-1"
    assert payload["job_id"] == "job-1"
    assert payload["project_id"] == "proj-1"
    assert "abcdef123456789" not in payload["message"]


def test_log_context_resets_after_the_block():
    with adflow_logging.LogContext(request_id="req-2"):
        assert adflow_logging.request_id_var.get() == "req-2"
    assert adflow_logging.request_id_var.get() == ""


# --------------------------------------------------------------------------
# Health / readiness
# --------------------------------------------------------------------------
def test_health_is_cheap_and_always_answers(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["app"]


def test_readiness_reports_every_dependency(client):
    response = client.get("/ready")
    body = response.json()
    assert response.status_code in (200, 503)
    assert set(body["checks"]) == {"database", "storage", "queue", "render"}
    assert body["checks"]["database"]["ok"] is True


def test_request_id_is_echoed(client):
    response = client.get("/health", headers={"X-Request-Id": "trace-me"})
    assert response.headers.get("X-Request-Id") == "trace-me"


# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------
def test_production_refuses_a_wildcard_cors_policy(monkeypatch):
    from app.main import _cors_origins

    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["*"])
    assert _cors_origins() == []

    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://adflow-ai-tadafq.netlify.app"])
    assert _cors_origins() == ["https://adflow-ai-tadafq.netlify.app"]


# --------------------------------------------------------------------------
# Webhooks
# --------------------------------------------------------------------------
def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_an_unsigned_webhook_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_SECRET", "shared-secret")
    response = client.post(f"{API}/webhooks/runway", json={"job_id": "x"})
    assert response.status_code == 401


def test_a_webhook_without_a_configured_secret_fails_closed(client, monkeypatch):
    """No secret means we cannot verify, so we must not accept."""
    monkeypatch.setattr(settings, "WEBHOOK_SECRET", None)
    monkeypatch.setattr(settings, "RUNWAY_WEBHOOK_SECRET", None)
    body = {"job_id": "x"}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    response = client.post(f"{API}/webhooks/runway", json=body,
                           headers={"X-Signature": _sign("anything", raw)})
    assert response.status_code == 401


def test_an_unknown_provider_path_is_not_accepted(client, monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_SECRET", "shared-secret")
    response = client.post(f"{API}/webhooks/notaprovider", json={"job_id": "x"})
    assert response.status_code == 404


def test_a_signed_webhook_updates_the_job_and_is_idempotent(client, db, make_project, monkeypatch):
    from app.models import GenerationJob
    from app.services.jobs import create_job

    monkeypatch.setattr(settings, "WEBHOOK_SECRET", "shared-secret")
    project = make_project(name="ويب هوك")
    job = create_job(db, project=project, job_type=JobType.VIDEO_GENERATION.value,
                     payload={"scene_number": 1})
    db.commit()

    body = {"job_id": job.id, "status": "succeeded", "output_url": "https://cdn/x.mp4"}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    headers = {"X-Signature": _sign("shared-secret", raw), "X-Delivery-Id": "delivery-1"}

    first = client.post(f"{API}/webhooks/runway", json=body, headers=headers)
    assert first.status_code == 202 and first.json()["ok"] is True

    second = client.post(f"{API}/webhooks/runway", json=body, headers=headers)
    assert second.status_code == 202
    assert second.json()["duplicate"] is True

    db.expire_all()
    stored = db.get(GenerationJob, job.id)
    assert stored.result["provider_output_url"] == "https://cdn/x.mp4"
    assert len(stored.result["_webhook_deliveries"]) == 1


def test_a_failure_callback_marks_the_job_failed(client, db, make_project, monkeypatch):
    from app.models import GenerationJob
    from app.services.jobs import create_job

    monkeypatch.setattr(settings, "WEBHOOK_SECRET", "shared-secret")
    project = make_project(name="فشل")
    job = create_job(db, project=project, job_type=JobType.VIDEO_GENERATION.value)
    db.commit()

    body = {"job_id": job.id, "status": "failed", "error": "provider ran out of capacity"}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    client.post(f"{API}/webhooks/veo", json=body,
                headers={"X-Signature": _sign("shared-secret", raw)})
    db.expire_all()
    assert db.get(GenerationJob, job.id).status == JobStatus.FAILED.value


def test_webhook_health_never_reveals_the_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_SECRET", "shared-secret")
    body = client.get(f"{API}/webhooks/runway/health").json()
    assert body["signature_verification_configured"] is True
    assert "shared-secret" not in json.dumps(body)


# --------------------------------------------------------------------------
# Job idempotency and cancellation
# --------------------------------------------------------------------------
def test_identical_work_does_not_become_two_jobs(db, make_project):
    from app.services.jobs import create_job

    project = make_project(name="تكرار")
    first = create_job(db, project=project, job_type=JobType.VIDEO_GENERATION.value,
                       scene_id=None, payload={"scene_number": 2})
    second = create_job(db, project=project, job_type=JobType.VIDEO_GENERATION.value,
                        scene_id=None, payload={"scene_number": 2})
    assert first.id == second.id


def test_a_different_scene_is_a_different_job(db, make_project):
    from app.services.jobs import create_job

    project = make_project(name="مشاهد")
    first = create_job(db, project=project, job_type=JobType.VIDEO_GENERATION.value,
                       payload={"scene_number": 1})
    second = create_job(db, project=project, job_type=JobType.VIDEO_GENERATION.value,
                        payload={"scene_number": 2})
    assert first.id != second.id


def test_only_one_worker_can_claim_a_job(db, make_project):
    from app.services.jobs import claim_job, create_job

    project = make_project(name="سباق")
    job = create_job(db, project=project, job_type=JobType.PHOTO_MOTION.value)
    db.commit()
    assert claim_job(db, job.id) is not None
    assert claim_job(db, job.id) is None, "a second worker must not get the same job"


def test_cancelling_a_queued_job_spends_nothing(db, make_project):
    from app.services.jobs import cancel_job, create_job

    project = make_project(name="إلغاء")
    job = create_job(db, project=project, job_type=JobType.VIDEO_GENERATION.value)
    db.commit()
    result = cancel_job(db, job)
    assert result["ok"] and result["status"] == JobStatus.CANCELLED.value
    assert result["provider_side"] is False
    assert "ما انصرف" in result["message_ar"]


def test_cancelling_a_provider_job_is_honest_about_cost(db, make_project):
    from app.services.jobs import cancel_job, create_job

    project = make_project(name="إلغاء مزود")
    job = create_job(db, project=project, job_type=JobType.VIDEO_GENERATION.value)
    job.status = JobStatus.RUNNING.value
    job.result = {"provider_job_id": "prov-123"}
    db.commit()
    result = cancel_job(db, job)
    assert result["provider_side"] is True
    assert "cost" in result["message_en"].lower()


def test_cancelling_a_finished_job_is_refused(db, make_project):
    from app.services.jobs import cancel_job, create_job

    project = make_project(name="خلصت")
    job = create_job(db, project=project, job_type=JobType.PHOTO_MOTION.value)
    job.status = JobStatus.COMPLETED.value
    db.commit()
    assert cancel_job(db, job)["ok"] is False
