"""Analysis must never run inside the HTTP request.

`POST /analysis/run` called `run_analysis` inline. On mock providers that is
instant, so every test passed and the screen worked. Against the real writer
each `complete_json` call is tens of seconds; the whole chain ran about ninety,
the browser gave up at roughly forty with "ما نكدر نوصل لسيرفر أدفلو", and the
request was torn down mid-transaction — so the analysis was not merely unseen,
it was gone. `GET /analysis` afterwards still reported no analysis.

These tests pin the contract that makes that impossible: the request queues,
something else does the work.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from app.core.db import time_key
from app.core.enums import JobType, ProjectState
from app.models import GenerationJob, Project
from app.services import jobs as jobs_service

API = "/api/v1"
APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"


@pytest.fixture
def no_dispatch(monkeypatch):
    """Hold the job at QUEUED so the request's own behaviour is observable.

    With the real thread pool the mock provider finishes before the assertion
    runs, and a synchronous implementation would pass these tests too.
    """
    from app.api import workflow

    monkeypatch.setattr(workflow, "dispatch", lambda job_id: None)


def test_run_queues_a_job_and_does_not_produce_the_analysis(client, make_project, no_dispatch):
    project = make_project(name="تحليل غير متزامن")
    body = client.post(f"{API}/projects/{project.id}/analysis/run").json()

    assert body["job"]["job_type"] == JobType.ANALYSIS.value
    assert body["job"]["status"] == "queued"
    # The request itself produced nothing — that is the whole point.
    assert body["analysis"] is None
    assert body["state"] == ProjectState.ANALYZING.value


def test_the_job_produces_the_analysis_and_advances_the_state(client, db, make_project, no_dispatch):
    project = make_project(name="تحليل يكمل")
    pid = project.id
    job_id = client.post(f"{API}/projects/{pid}/analysis/run").json()["job"]["id"]

    jobs_service.execute_job(db, job_id)

    payload = client.get(f"{API}/projects/{pid}/analysis").json()
    assert payload["job"]["status"] == "completed", payload["job"].get("error_message")
    assert payload["analysis"]["readiness_score"] >= 0
    assert payload["analysis"]["director_notes"]
    assert payload["state"] == ProjectState.ANALYSIS_READY.value


def test_the_status_is_pollable_before_the_job_runs(client, make_project, no_dispatch):
    """`GET /analysis` is the client's only window into a queued job.

    Without the job in this payload a failed analysis is indistinguishable
    from one that never started: an empty screen, forever.
    """
    project = make_project(name="استعلام")
    pid = project.id
    client.post(f"{API}/projects/{pid}/analysis/run")

    payload = client.get(f"{API}/projects/{pid}/analysis").json()
    assert payload["job"]["status"] == "queued"
    assert payload["analysis"] is None


def test_a_double_click_does_not_become_two_analyses(client, make_project, no_dispatch):
    project = make_project(name="ضغطتين")
    pid = project.id
    first = client.post(f"{API}/projects/{pid}/analysis/run").json()["job"]["id"]
    second = client.post(f"{API}/projects/{pid}/analysis/run").json()["job"]["id"]
    assert first == second


def test_a_failed_job_is_visible_rather_than_silent(client, db, make_project, no_dispatch, monkeypatch):
    project = make_project(name="فشل التحليل")
    pid = project.id
    job_id = client.post(f"{API}/projects/{pid}/analysis/run").json()["job"]["id"]

    from app.services import stage_jobs

    def _explode(*args, **kwargs):
        raise RuntimeError("provider refused")

    monkeypatch.setattr(stage_jobs, "run_analysis", _explode)
    jobs_service.execute_job(db, job_id)

    payload = client.get(f"{API}/projects/{pid}/analysis").json()
    assert payload["job"]["status"] == "failed"
    assert "provider refused" in payload["job"]["error_message"]
    # The project stays in ANALYZING rather than claiming a report exists.
    assert payload["analysis"] is None


def test_a_rerun_from_a_later_stage_does_not_drag_the_project_backwards(client, db, make_project, no_dispatch):
    """Re-analysing mid-workflow must not silently undo approvals.

    The handler advances only a project that is still ANALYZING.
    """
    project = make_project(name="إعادة تحليل")
    pid = project.id
    job_id = client.post(f"{API}/projects/{pid}/analysis/run").json()["job"]["id"]
    jobs_service.execute_job(db, job_id)
    client.post(f"{API}/projects/{pid}/analysis/approve")
    assert client.get(f"{API}/projects/{pid}/analysis").json()["state"] == ProjectState.CONCEPT_REVIEW.value

    stale = db.query(GenerationJob).filter(GenerationJob.project_id == pid).first()
    stale.status = "completed"
    db.commit()

    # A second run from CONCEPT_REVIEW leaves the state where the user put it.
    second = client.post(f"{API}/projects/{pid}/analysis/run").json()
    assert second["state"] == ProjectState.CONCEPT_REVIEW.value
    jobs_service.execute_job(db, second["job"]["id"])
    db.expire_all()
    assert db.get(Project, pid).state == ProjectState.CONCEPT_REVIEW.value


# --------------------------------------------------------------------------
# The bug class, not just this instance
# --------------------------------------------------------------------------
def _created_job_types() -> set[str]:
    """Every `JobType.X` handed to `create_job` anywhere in app/."""
    found: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name != "create_job":
                continue
            for keyword in node.keywords:
                if keyword.arg != "job_type":
                    continue
                for sub in ast.walk(keyword.value):
                    if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Attribute):
                        if getattr(sub.value.value, "id", "") == "JobType":
                            found.add(getattr(JobType, sub.value.attr).value)
    return found


def test_every_job_type_the_code_creates_has_a_handler():
    """A job type with no handler fails in a thread, where nobody is looking.

    `JobType.ANALYSIS` sat in the enum for weeks with nothing registered for
    it. Creating one would have set the job FAILED with "No handler
    registered" — in the background, with the UI still spinning.
    """
    import app.services.production  # noqa: F401  (registers the production handlers)
    import app.services.stage_jobs  # noqa: F401  (registers the writing-stage handlers)

    created = _created_job_types()
    assert created, "the scan found no create_job call sites — the scan is broken, not the code"
    missing = sorted(created - set(jobs_service._HANDLERS))
    assert not missing, f"jobs are created for these types but nothing handles them: {missing}"


# --------------------------------------------------------------------------
# Sorting timestamps across a session boundary
# --------------------------------------------------------------------------
def test_time_key_sorts_a_stored_row_against_a_fresh_one():
    """Postgres returns aware datetimes, SQLite naive ones, `utcnow()` aware.

    `/production/start` sorts `project.jobs`; once analysis became a job, that
    list held a committed row and freshly-created ones at the same time and
    raised "can't compare offset-naive and offset-aware datetimes".
    """
    from datetime import datetime, timezone

    naive = datetime(2026, 1, 1, 12, 0, 0)
    aware = datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    assert sorted([aware, naive], key=time_key) == [naive, aware]
    assert time_key(None) < time_key(naive)


# --------------------------------------------------------------------------
# The other three stages — same contract
# --------------------------------------------------------------------------
#: stage -> (start endpoint, report endpoint, the key its artifact lives under)
STAGES = {
    "concepts": ("/concepts/generate", "/concepts", "items"),
    "script": ("/script/generate", "/script", "variants"),
    "storyboard": ("/storyboard/generate", "/storyboard", "storyboard"),
}


@pytest.mark.parametrize("name", sorted(STAGES))
def test_each_writing_stage_queues_instead_of_working(client, db, make_project, stage, monkeypatch, name):
    """Concepts, script and storyboard all call the LLM too.

    The script is the worst of them: three variants, three sequential calls.
    Fixing only the analysis would have moved the same failure one screen
    along, so all four queue.
    """
    project = make_project(name=f"مرحلة {name}")
    pid = project.id
    # Walk up to the stage under test with everything before it finished.
    stage(pid, "analysis")
    client.post(f"{API}/projects/{pid}/analysis/approve")
    if name in ("script", "storyboard"):
        stage(pid, "concepts")
        concepts = client.get(f"{API}/projects/{pid}/concepts").json()
        client.post(f"{API}/projects/{pid}/concepts/approve", json={"entity_id": concepts["items"][0]["id"]})
    if name == "storyboard":
        stage(pid, "script")
        scripts = client.get(f"{API}/projects/{pid}/script").json()
        client.post(f"{API}/projects/{pid}/script/approve", json={"entity_id": scripts["variants"][0]["id"]})

    # Only now hold the queue still, so the stage under test is the one
    # observed — the walk-up above needed the real thread pool.
    from app.api import workflow

    monkeypatch.setattr(workflow, "dispatch", lambda job_id: None)

    start, report, artifact = STAGES[name]
    body = client.post(f"{API}/projects/{pid}{start}").json()
    assert body["job"]["job_type"] == name
    assert body["job"]["status"] == "queued"
    assert not body[artifact], "the request produced the artifact instead of queuing the work"

    jobs_service.execute_job(db, body["job"]["id"])
    done = client.get(f"{API}/projects/{pid}{report}").json()
    assert done["job"]["status"] == "completed", done["job"].get("error_message")
    assert done[artifact]


@pytest.mark.parametrize("name", sorted(STAGES))
def test_the_approval_gate_refuses_before_a_job_is_created(client, make_project, no_dispatch, name):
    """The gate must still close on the request, not inside the worker.

    A stage that queued first and checked later would answer 200, spin in the
    UI, and fail in a thread — the user would see "working" for a rule the
    product could have stated instantly.
    """
    project = make_project(name=f"بوابة {name}")
    start, _, _ = STAGES[name]
    refused = client.post(f"{API}/projects/{project.id}{start}")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "approval_required"
    assert not project.jobs
