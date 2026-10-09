"""Celery reliability (Phase 7 §10-12): retry classification, backoff, the dead-letter table, housekeeping,
beat expiry, task limits and request-id propagation."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from celery.exceptions import Retry
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.config import settings
from app.models.operations import FailedJob
from app.worker import failure


def http_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://provider.example/fixtures?apikey=SECRETKEY123")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(code, request=request))


def validation_error() -> ValidationError:
    class M(BaseModel):
        x: int

    try:
        M(x="not a number")
    except ValidationError as exc:
        return exc
    raise AssertionError


# -- classification --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc,expected",
    [
        (httpx.ReadTimeout("slow"), failure.TEMPORARY),
        (httpx.ConnectError("refused"), failure.TEMPORARY),
        (http_error(429), failure.TEMPORARY),
        (http_error(503), failure.TEMPORARY),
        (http_error(408), failure.TEMPORARY),
        (http_error(401), failure.AUTHENTICATION),
        (http_error(403), failure.AUTHENTICATION),
        (http_error(404), failure.PERMANENT),
        (http_error(422), failure.VALIDATION),
        (OperationalError("SELECT 1", {}, ConnectionResetError()), failure.DATABASE),
        (validation_error(), failure.VALIDATION),
        (KeyError("home_team"), failure.VALIDATION),
        (ValueError("bad"), failure.VALIDATION),
        (IntegrityError("INSERT", {}, Exception("duplicate key")), failure.PERMANENT),
        (RuntimeError("a bug"), failure.PERMANENT),
    ],
)
def test_failures_are_classified(exc, expected):
    assert failure.classify(exc) == expected


def test_only_temporary_and_database_failures_are_retryable():
    assert failure.is_retryable(httpx.ReadTimeout("x"))
    assert failure.is_retryable(OperationalError("q", {}, ConnectionResetError()))
    for exc in (http_error(401), ValueError("x"), RuntimeError("bug"), validation_error()):
        assert not failure.is_retryable(exc)


def test_the_providers_own_give_up_signal_is_retried_later():
    from app.worker.provider_guard import ProviderUnavailableError

    assert failure.classify(ProviderUnavailableError("get_live failed after 3 attempts")) == failure.TEMPORARY


# -- backoff -------------------------------------------------------------------------------------------


def test_backoff_grows_exponentially_with_jitter_and_is_capped():
    delays = [failure.backoff_seconds(n) for n in range(0, 4)]
    for n, delay in enumerate(delays):
        base = 10 * 2**n
        assert base <= delay <= base * 1.25
    assert failure.backoff_seconds(30) <= 600 * 1.25


# -- retry_or_raise ---------------------------------------------------------------------------------------


class FakeTask:
    name = "app.worker.fake.task"
    max_retries = 3

    def __init__(self, retries=0):
        self.request = SimpleNamespace(retries=retries)
        self.retried_with = None

    def retry(self, countdown, exc):
        self.retried_with = countdown
        return Retry(exc=exc)


def test_a_temporary_failure_is_retried_with_backoff():
    task = FakeTask(retries=1)
    with pytest.raises(Retry):
        failure.retry_or_raise(task, httpx.ReadTimeout("slow"))
    assert 20 <= task.retried_with <= 25


def test_a_permanent_failure_is_not_retried_but_raised_for_recording():
    task = FakeTask()
    with pytest.raises(RuntimeError, match="a bug"):
        failure.retry_or_raise(task, RuntimeError("a bug"))
    assert task.retried_with is None


def test_an_authentication_failure_is_not_retried():
    task = FakeTask()
    with pytest.raises(httpx.HTTPStatusError):
        failure.retry_or_raise(task, http_error(401))
    assert task.retried_with is None


def test_retries_stop_at_the_maximum():
    task = FakeTask(retries=3)
    with pytest.raises(httpx.ReadTimeout):
        failure.retry_or_raise(task, httpx.ReadTimeout("still slow"))
    assert task.retried_with is None


def test_every_retrying_task_uses_the_classifier_not_a_blind_fixed_retry():
    import pathlib
    import re

    worker_dir = pathlib.Path(__file__).parent.parent / "app" / "worker"
    offenders = [p.name for p in worker_dir.glob("*.py") if re.search(r"raise self\.retry\(countdown=\d", p.read_text(encoding="utf8"))]
    assert offenders == []


# -- scrubbing -----------------------------------------------------------------------------------------------


def test_error_text_never_carries_credentials():
    text = (
        "Client error '401' for url 'https://v3.football.api-sports.io/fixtures?live=all&apikey=abcd1234' "
        "password=hunter2 Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig token=abc123 "
        + "A" * 60
    )
    scrubbed = failure.scrub(text)
    for leaked in ("abcd1234", "hunter2", "abc123", "A" * 40):
        assert leaked not in scrubbed
    assert "https://v3.football.api-sports.io/fixtures" in scrubbed  # the useful part survives


def test_scrubbed_text_is_bounded():
    assert len(failure.scrub("x " * 5000)) <= 1000


def test_the_entity_comes_from_the_tasks_id_argument():
    def sync_team(team_id: int, force: bool = False): ...

    task = SimpleNamespace(run=sync_team)
    assert failure.describe_entity(task, (42,), {}) == "team:42"
    assert failure.describe_entity(task, (), {"team_id": 7}) == "team:7"
    assert failure.describe_entity(SimpleNamespace(run=lambda: None), (), {}) is None


# -- the dead-letter table -----------------------------------------------------------------------------------------


async def _record(session_factory, exc, **overrides):
    args = dict(task_name="app.worker.tasks.sync_team", task_id="abc-123", exc=exc, retries=3, entity="team:9", args_summary="((9,), {})", request_id="req-1")
    args.update(overrides)
    await failure.record_failure(session_factory=session_factory, **args)


async def test_a_failed_job_is_recorded_with_everything_an_operator_needs(session_factory):
    await _record(session_factory, http_error(503))
    async with session_factory() as db:
        job = await db.scalar(select(FailedJob))
    assert job.task_name == "app.worker.tasks.sync_team"
    assert job.error_type == "HTTPStatusError"
    assert job.classification == failure.TEMPORARY
    assert job.retries == 3 and job.entity == "team:9" and job.request_id == "req-1"
    assert job.failed_at and job.resolved_at is None
    assert "SECRETKEY123" not in job.error_message


async def test_repeated_identical_failures_fold_into_one_row_with_a_count(session_factory):
    for _ in range(5):
        await _record(session_factory, RuntimeError("same bug"))
    async with session_factory() as db:
        rows = (await db.scalars(select(FailedJob))).all()
    assert len(rows) == 1 and rows[0].occurrences == 5


async def test_different_entities_or_errors_are_separate_rows(session_factory):
    await _record(session_factory, RuntimeError("bug"), entity="team:1")
    await _record(session_factory, RuntimeError("bug"), entity="team:2")
    await _record(session_factory, ValueError("other"), entity="team:1")
    async with session_factory() as db:
        assert len((await db.scalars(select(FailedJob))).all()) == 3


async def test_a_resolved_failure_that_recurs_is_a_new_row(session_factory):
    await _record(session_factory, RuntimeError("bug"))
    async with session_factory() as db:
        job = await db.scalar(select(FailedJob))
        job.resolved_at = datetime.now(timezone.utc)
        await db.commit()
    await _record(session_factory, RuntimeError("bug"))
    async with session_factory() as db:
        assert len((await db.scalars(select(FailedJob))).all()) == 2


async def test_recording_a_failure_never_raises_into_the_worker(monkeypatch):
    from app.worker import async_runner

    def broken(_coro):
        _coro.close()
        raise ConnectionError("database is down")

    monkeypatch.setattr(async_runner, "run", broken)
    failure.on_task_failure(SimpleNamespace(name="t", request=SimpleNamespace(retries=0), run=lambda: None), "id", RuntimeError("x"), (), {})  # must not raise


# -- housekeeping ---------------------------------------------------------------------------------------------------


async def test_old_operational_data_is_purged_and_recent_data_kept(session_factory, make_user):
    from app.models.session import PasswordResetToken, RefreshToken
    from app.worker.ops_tasks import purge_operational_data

    user, _ = await make_user("purge@example.com")
    now = datetime.now(timezone.utc)
    async with session_factory() as db:
        db.add_all(
            [
                FailedJob(task_name="t", error_type="E", classification="permanent", failed_at=now - timedelta(days=100)),
                FailedJob(task_name="t", error_type="E2", classification="permanent", failed_at=now - timedelta(days=40), resolved_at=now - timedelta(days=35)),
                FailedJob(task_name="t", error_type="E3", classification="permanent", failed_at=now - timedelta(days=2)),
                RefreshToken(user_id=user.id, token_hash="a" * 64, expires_at=now - timedelta(days=30)),
                RefreshToken(user_id=user.id, token_hash="b" * 64, expires_at=now + timedelta(days=30)),
                PasswordResetToken(user_id=user.id, token_hash="c" * 64, expires_at=now - timedelta(days=30)),
            ]
        )
        await db.commit()
        counts = await purge_operational_data(db, now)
    assert counts == {"failed_jobs_resolved": 1, "failed_jobs_old": 1, "refresh_tokens": 1, "reset_tokens": 1}
    async with session_factory() as db:
        assert [j.error_type for j in (await db.scalars(select(FailedJob))).all()] == ["E3"]
        assert [t.token_hash for t in (await db.scalars(select(RefreshToken))).all()] == ["b" * 64]
        again = await purge_operational_data(db, now)
    assert sum(again.values()) == 0  # idempotent


# -- celery configuration ------------------------------------------------------------------------------------------------


def test_tasks_have_time_limits_and_are_redelivered_if_a_worker_dies():
    from app.worker.celery_app import celery_app

    conf = celery_app.conf
    assert conf.task_soft_time_limit == settings.celery_task_soft_time_limit_seconds
    assert conf.task_time_limit == settings.celery_task_time_limit_seconds
    assert conf.task_soft_time_limit < conf.task_time_limit
    assert conf.task_acks_late and conf.task_reject_on_worker_lost
    assert conf.broker_transport_options["visibility_timeout"] > conf.task_time_limit


def test_every_scheduled_task_expires_so_an_outage_does_not_pile_up_a_backlog():
    from app.worker.celery_app import celery_app

    assert celery_app.conf.beat_schedule
    for name, entry in celery_app.conf.beat_schedule.items():
        assert entry["options"]["expires"] >= 30, name
        assert entry["options"]["expires"] >= int(entry["schedule"]), name
        assert entry["task"] in celery_app.tasks, f"{name} schedules an unregistered task"


def test_the_originating_request_id_travels_with_the_task_message():
    from app.core.logging_config import request_id_var
    from app.worker.celery_app import _propagate_request_id

    token = request_id_var.set("req-from-the-api")
    try:
        headers: dict = {}
        _propagate_request_id(headers=headers)
        assert headers["request_id"] == "req-from-the-api"
    finally:
        request_id_var.reset(token)


def test_the_worker_adopts_the_request_id_of_the_task_it_runs():
    from app.core.logging_config import request_id_var
    from app.worker.celery_app import _log_task_finished, _on_task_prerun

    task = SimpleNamespace(request=SimpleNamespace(request_id="req-from-the-api", get=lambda k, d=None: "req-from-the-api"), name="t")
    _on_task_prerun(task_id="task-1234567890abcdef", task=task)
    assert request_id_var.get() == "req-from-the-api"
    _log_task_finished(task_id="task-1234567890abcdef", task=task, state="SUCCESS")
    assert request_id_var.get() is None
