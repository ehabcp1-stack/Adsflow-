"""A model call gets one wall-clock budget, not two multiplied retry counts.

Measured live: an analysis job ran 212 seconds and was still going, with the
database answering in 79ms — so the model call was the whole of it. It had no
effective ceiling at all, because two retry layers multiplied:

    _complete_json_with_repair   2 attempts
    http._request                3 attempts x PROVIDER_TIMEOUT_SEC (120s)
    ------------------------------------------------------------------
    2 x 3 x 120s + backoff    =  ~12 minutes of silence

Nobody chose twelve minutes. It fell out of two reasonable-looking numbers,
and a count-based bound is exactly the kind that multiplies when someone wraps
it. A wall-clock budget cannot be multiplied, so that is what bounds it now.
"""
from __future__ import annotations

import time

import pytest

from app.core.config import settings
from app.providers import http


def test_the_budget_cannot_be_multiplied_by_the_layers_above_it():
    """The property that matters, stated once.

    Whatever the retry counts become, one completion may not outlive its
    budget by more than a single in-flight attempt.
    """
    worst_case = settings.LLM_TOTAL_BUDGET_SEC + settings.LLM_TIMEOUT_SEC
    naive_multiplied = 2 * (settings.PROVIDER_MAX_RETRIES + 1) * settings.PROVIDER_TIMEOUT_SEC
    assert worst_case < naive_multiplied
    # And it stays inside what the job system is willing to wait for.
    assert worst_case < settings.JOB_STALE_AFTER_SEC


def test_an_expired_deadline_refuses_before_spending_another_call(monkeypatch):
    calls = []

    def _never_called(*args, **kwargs):  # pragma: no cover - must not run
        calls.append(1)
        raise AssertionError("a request was made after the budget was gone")

    monkeypatch.setattr(http.httpx, "Client", _never_called)
    with pytest.raises(http.ProviderHttpError) as excinfo:
        http.post_json("https://example.invalid/v1/messages", deadline=time.monotonic() - 1)

    assert excinfo.value.kind == http.ErrorKind.TIMEOUT
    assert not calls


def test_no_single_attempt_may_outlive_the_remaining_budget(monkeypatch):
    """A 60s attempt started with 5s left would blow the budget by 55s."""
    seen = {}

    class _Client:
        def __init__(self, timeout=None):
            seen["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def request(self, *a, **k):
            raise http.httpx.ConnectError("no network in tests")

    monkeypatch.setattr(http.httpx, "Client", _Client)
    with pytest.raises(http.ProviderHttpError):
        http.post_json(
            "https://example.invalid/v1/messages",
            timeout=60.0,
            max_retries=0,
            deadline=time.monotonic() + 5,
        )
    assert seen["timeout"] <= 5.0


def test_the_repair_attempt_is_skipped_once_the_budget_is_gone():
    """The second vendor call is the one that doubles the bill and the wait."""
    from app.providers.adapters import _complete_json_with_repair

    attempts = []

    def make_request(instruction):
        attempts.append(instruction)
        return {"not": "valid for this task"}

    ok, payload, raw, errors = _complete_json_with_repair(
        task="brief_interpretation",
        make_request=make_request,
        extract_text=lambda raw: "{}",
        deadline=time.monotonic() - 1,
    )
    assert not ok
    assert len(attempts) == 1, "the repair call ran even though the time was up"
    assert any("ran out of time" in e for e in errors)


def test_the_repair_attempt_still_happens_inside_the_budget():
    """The guard must not cost us the repair on a healthy call."""
    from app.providers.adapters import _complete_json_with_repair

    attempts = []

    def make_request(instruction):
        attempts.append(instruction)
        return {}

    _complete_json_with_repair(
        task="brief_interpretation",
        make_request=make_request,
        extract_text=lambda raw: "{}",
        deadline=time.monotonic() + 60,
    )
    assert len(attempts) == 2
