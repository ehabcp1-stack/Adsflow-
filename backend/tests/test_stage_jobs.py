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

from app.core.config import settings
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


# --------------------------------------------------------------------------
# A job nothing is working on must not look like one that is
# --------------------------------------------------------------------------
def _age_job(db, job_id: str, seconds: float) -> None:
    """Backdate a RUNNING job so it looks abandoned."""
    from datetime import timedelta

    from app.core.db import utcnow

    job = db.get(GenerationJob, job_id)
    job.status = "running"
    job.started_at = utcnow() - timedelta(seconds=seconds)
    job.progress = 0.15
    job.progress_label = "understanding the brief"
    db.commit()


def test_a_job_orphaned_by_a_restart_is_failed_at_startup(client, db, make_project, no_dispatch):
    """The inline pool lives in this process; a RUNNING job at boot is dead.

    Found live: an analysis job sat at `running`, progress 0.15, for 19
    minutes after a deploy restarted the container. Nothing would ever have
    moved it, and the screen polled it forever.
    """
    project = make_project(name="انقطع السيرفر")
    pid = project.id
    job_id = client.post(f"{API}/projects/{pid}/analysis/run").json()["job"]["id"]
    _age_job(db, job_id, seconds=5)  # young, but the process is restarting

    # Scoped to this project: the suite runs real background jobs for other
    # projects, and a test that reaped the whole table would fail them.
    assert jobs_service.reap_stale_jobs(db, all_running=True, project_id=pid) == 1

    payload = client.get(f"{API}/projects/{pid}/analysis").json()
    assert payload["job"]["status"] == "failed"
    assert "restarted" in payload["job"]["error_message"]


def test_a_stale_job_does_not_block_the_retry(client, db, make_project, no_dispatch):
    """The dead-end this closes.

    `find_active_duplicate` handed the abandoned job back to every retry and
    `execute_job` refuses to touch a RUNNING one — so the stage could not be
    run again by anything the UI offered. A stuck job was not a delay, it was
    a project that could never move.
    """
    project = make_project(name="ما ينعاد")
    pid = project.id
    first = client.post(f"{API}/projects/{pid}/analysis/run").json()["job"]["id"]
    _age_job(db, first, seconds=settings.JOB_STALE_AFTER_SEC + 60)

    second = client.post(f"{API}/projects/{pid}/analysis/run").json()["job"]
    assert second["id"] != first, "the retry was handed the dead job again"
    assert second["status"] == "queued"

    db.expire_all()
    assert db.get(GenerationJob, first).status == "failed"

    jobs_service.execute_job(db, second["id"])
    assert client.get(f"{API}/projects/{pid}/analysis").json()["analysis"] is not None


def test_a_slow_but_living_job_is_left_alone(client, db, make_project, no_dispatch):
    """The ceiling sits above the provider's own, so slow is not dead.

    Three attempts at PROVIDER_TIMEOUT_SEC plus backoff is about six minutes;
    reaping below that would kill work that was about to finish.
    """
    project = make_project(name="بطيء بس شغال")
    job_id = client.post(f"{API}/projects/{project.id}/analysis/run").json()["job"]["id"]
    _age_job(db, job_id, seconds=settings.JOB_STALE_AFTER_SEC - 60)

    assert jobs_service.reap_stale_jobs(db) == 0
    assert db.get(GenerationJob, job_id).status == "running"


def test_the_stale_ceiling_is_above_the_provider_ceiling():
    """Pinned as a relationship, not a number — either may be retuned."""
    provider_ceiling = settings.PROVIDER_TIMEOUT_SEC * (settings.PROVIDER_MAX_RETRIES + 1)
    assert settings.JOB_STALE_AFTER_SEC > provider_ceiling


# --------------------------------------------------------------------------
# Two model calls that do not read each other should not be paid for in series
# --------------------------------------------------------------------------
def test_the_two_analysis_model_calls_overlap(db, make_project, monkeypatch):
    """`brief_interpretation` and `creative_strategy` run side by side.

    In series the stage costs two ~28s calls for no reason: neither reads the
    other's output. This asserts overlap rather than a wall-clock number, so
    it stays true on a fast machine and on a slow one.
    """
    import threading
    import time

    from app.services import analysis as analysis_service

    inside = threading.Barrier(2, timeout=5)
    real = analysis_service.get_llm()

    class _Overlapping:
        def complete_json(self, *, task, context):
            if task in ("brief_interpretation", "creative_strategy"):
                # Neither call can pass this point alone: if they were
                # sequential, the first would time out waiting here.
                inside.wait()
                time.sleep(0.01)
            return real.complete_json(task=task, context=context)

    monkeypatch.setattr(analysis_service, "get_llm", lambda *a, **k: _Overlapping())
    project = make_project(name="توازي")
    analysis = analysis_service.run_analysis(db, project)
    assert analysis.brief_interpretation and analysis.creative_strategy


# --------------------------------------------------------------------------
# A database error must not be able to produce a job nobody can finish
# --------------------------------------------------------------------------
def test_a_failing_write_still_records_the_job_as_failed(client, db, make_project, no_dispatch, monkeypatch):
    """The exact shape of the live failure, in miniature.

    A model-written Arabic angle longer than its `varchar(40)` column made
    Postgres refuse the INSERT. That poisons the Session, so the commit meant
    to record the failure raised too, and the row stayed RUNNING with nothing
    running it — unkillable, and unrepeatable because the idempotency check
    handed the dead job back to every retry. The failure must be recorded on a
    session that cannot have inherited the broken transaction.
    """
    project = make_project(name="فشل بالكتابة")
    pid = project.id
    job_id = client.post(f"{API}/projects/{pid}/analysis/run").json()["job"]["id"]

    from app.services import stage_jobs

    def _poison(*args, **kwargs):
        raise RuntimeError("value too long for type character varying(40)")

    monkeypatch.setattr(stage_jobs, "run_analysis", _poison)
    jobs_service.execute_job(db, job_id)

    payload = client.get(f"{API}/projects/{pid}/analysis").json()
    assert payload["job"]["status"] == "failed", "the job was left claiming to run"
    assert "varying(40)" in payload["job"]["error_message"]


def test_a_model_answer_longer_than_its_column_is_stored_not_dropped(db, make_project, monkeypatch):
    """`fit` trims to the column instead of letting the INSERT fail.

    SQLite does not enforce the length, so this asserts the clamp itself
    rather than relying on the database to complain — which is precisely why
    the bug reached production with a green suite.
    """
    from app.core.db import fit
    from app.models import ProjectAnalysis
    from app.services import analysis as analysis_service

    long_angle = "الأمان العائلي والخصوصية والموقع القريب من المدارس والخدمات الأساسية"
    assert len(long_angle) > 40

    real = analysis_service.get_llm()

    class _Verbose:
        def complete_json(self, *, task, context):
            result = real.complete_json(task=task, context=context)
            if task == "creative_strategy":
                result.data["recommended_angle"] = long_angle
            return result

    monkeypatch.setattr(analysis_service, "get_llm", lambda *a, **k: _Verbose())
    project = make_project(name="زاوية طويلة")
    analysis = analysis_service.run_analysis(db, project)

    limit = ProjectAnalysis.__table__.columns["recommended_angle"].type.length
    assert len(analysis.recommended_angle) <= limit
    assert analysis.recommended_angle == fit(ProjectAnalysis, "recommended_angle", long_angle)
    assert analysis.recommended_angle  # trimmed, not blanked


def test_fit_reads_the_limit_from_the_column_so_the_two_cannot_drift():
    from app.core.db import fit
    from app.models import ProjectAnalysis

    limit = ProjectAnalysis.__table__.columns["recommended_angle"].type.length
    assert len(fit(ProjectAnalysis, "recommended_angle", "x" * (limit + 50))) == limit
    assert fit(ProjectAnalysis, "recommended_angle", None, "emotional") == "emotional"
    assert fit(ProjectAnalysis, "recommended_angle", "   ", "emotional") == "emotional"


# --------------------------------------------------------------------------
# The production screen reports production, not the project's whole history
# --------------------------------------------------------------------------
def test_production_status_ignores_the_writing_stages(client, db, make_project, stage):
    """A project that has not produced a frame must not report failures.

    Live: eleven jobs on the project — five completed writing stages, five
    analysis attempts killed by deploys, one cancelled — and the production
    screen counted all of them. It showed "5/11" and five red cards on a
    project whose production had never been started, which read exactly like a
    montage that had failed halfway.
    """
    from app.services.production import PRODUCTION_JOB_TYPES, production_status

    project = make_project(name="ما بدأ الإنتاج")
    pid = project.id
    stage(pid, "analysis")
    client.post(f"{API}/projects/{pid}/analysis/approve")
    stage(pid, "concepts")
    concepts = client.get(f"{API}/projects/{pid}/concepts").json()
    client.post(f"{API}/projects/{pid}/concepts/approve", json={"entity_id": concepts["items"][0]["id"]})
    stage(pid, "script")
    scripts = client.get(f"{API}/projects/{pid}/script").json()
    client.post(f"{API}/projects/{pid}/script/approve", json={"entity_id": scripts["variants"][0]["id"]})
    stage(pid, "storyboard")
    client.post(f"{API}/projects/{pid}/storyboard/approve")

    # Four writing jobs exist and all finished; none of them is production.
    db.expire_all()
    fresh = db.get(Project, pid)
    assert len(fresh.jobs) >= 4
    status = production_status(db, fresh)

    assert status["started"] is False
    assert status["jobs_total"] == 0
    assert status["jobs_failed"] == 0
    assert status["all_done"] is False, "an unstarted production must not look finished"
    assert all(j["type"] in PRODUCTION_JOB_TYPES for j in status["jobs"])


def test_an_interrupted_analysis_is_not_reported_as_a_production_failure(db, make_project):
    """The specific misreading: a dead writing job shown as a red card here."""
    from app.core.enums import JobType
    from app.services.production import production_status

    project = make_project(name="تحليل منقطع")
    dead = jobs_service.create_job(db, project=project, job_type=JobType.ANALYSIS.value)
    dead.status = "failed"
    dead.error_message = "The server restarted while this was running."
    db.commit()

    status = production_status(db, project)
    assert status["jobs_failed"] == 0
    assert status["jobs"] == []


def test_a_finished_job_is_never_reported_beside_a_stale_state(db, make_project):
    """The payload may not be older than the job status it carries.

    A stage GET used to read the project row first and the job row second.
    pysqlite runs each SELECT on its own, so the two reads can straddle the
    worker's commit: the response says `completed` and still carries the state
    from before the job ran. The client stops polling on `completed`, so the
    user is left on a screen that never advances — intermittently, and only
    for the job actually being watched. It surfaced as one flaky run of the
    end-to-end journey in a hundred, which is exactly how this class of bug
    announces itself.
    """
    from app.core.db import SessionLocal
    from app.core.enums import JobType, ProjectState
    from app.models import Project
    from app.services import stage_jobs

    project = make_project(name="حالة بايتة")
    job = jobs_service.create_job(db, project=project, job_type=JobType.ANALYSIS.value)
    db.commit()

    # This session has the project loaded and cached, exactly as the request
    # does after `get_project`.
    assert project.state == ProjectState.DRAFT.value

    worker = SessionLocal()
    try:
        theirs = worker.get(Project, project.id)
        theirs.state = ProjectState.ANALYSIS_READY.value
        worker.commit()
    finally:
        worker.close()

    stage_jobs.latest_job(db, project, JobType.ANALYSIS.value)
    assert project.state == ProjectState.ANALYSIS_READY.value, (
        "reading the job must leave the rest of the payload no older than it"
    )
    assert job.id
