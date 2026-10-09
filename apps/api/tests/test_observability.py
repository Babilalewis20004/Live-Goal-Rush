"""Structured logging and metrics (Phase 6)."""

import json
import logging

import pytest

from app.core.logging_config import JsonFormatter, log_event, request_id_var
from app.models.enums import UserRole

API = "/api/v1"


def _format(record_kwargs=None, *, event="article_publish", **fields):
    logger = logging.getLogger("tests.observability")
    record = logger.makeRecord("tests.observability", logging.INFO, __file__, 1, event, (), None, extra={"event": event, **fields})
    return json.loads(JsonFormatter("api").format(record))


def test_log_lines_are_single_json_objects_with_a_stable_event_name():
    line = _format(article_id=12, user_id=3)
    assert line["service"] == "api" and line["event"] == "article_publish" and line["level"] == "INFO"
    assert line["article_id"] == 12 and line["user_id"] == 3
    assert line["ts"].endswith("Z") and line["logger"] == "tests.observability"


def test_plain_messages_become_the_event():
    logger = logging.getLogger("tests.plain")
    record = logger.makeRecord("tests.plain", logging.WARNING, __file__, 1, "something odd: %s", ("x",), None)
    parsed = json.loads(JsonFormatter("worker").format(record))
    assert parsed["event"] == "something odd: x" and parsed["service"] == "worker" and parsed["level"] == "WARNING"


@pytest.mark.parametrize("key", ["password", "access_token", "Authorization", "cookie_header", "user_email", "client_secret"])
def test_sensitive_fields_are_redacted(key):
    assert _format(**{key: "hunter2"})[key] == "[redacted]"


def test_odd_values_do_not_break_formatting():
    line = _format(items={1, 2}, obj=object(), nested={"a": [1, {"b": None}]})
    assert sorted(line["items"]) == [1, 2] and isinstance(line["obj"], str) and line["nested"] == {"a": [1, {"b": None}]}


def test_exceptions_are_included_as_text():
    logger = logging.getLogger("tests.exc")
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logger.makeRecord("tests.exc", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    parsed = json.loads(JsonFormatter("api").format(record))
    assert "ValueError: boom" in parsed["exception"]


def test_the_request_id_rides_along_when_set():
    token = request_id_var.set("req-12345678")
    try:
        assert _format()["request_id"] == "req-12345678"
    finally:
        request_id_var.reset(token)
    assert "request_id" not in _format()


async def test_every_response_carries_a_request_id_and_a_sane_one_is_echoed(client):
    generated = (await client.get("/health")).headers["x-request-id"]
    assert len(generated) >= 8
    echoed = await client.get(f"{API}/articles", headers={"X-Request-ID": "trace-abc-12345"})
    assert echoed.headers["x-request-id"] == "trace-abc-12345"
    hostile = await client.get(f"{API}/articles", headers={"X-Request-ID": "x\r\nSet-Cookie: a=b"})
    assert "set-cookie" not in hostile.headers and hostile.headers["x-request-id"] != "x"


async def test_requests_are_logged_as_structured_events_without_sensitive_data(client, caplog):
    with caplog.at_level(logging.INFO):
        await client.get(f"{API}/articles", params={"tag": "secret-looking-tag"}, headers={"Authorization": "Bearer abc.def.ghi"})
    events = [r for r in caplog.records if getattr(r, "event", None) == "http_request"]
    assert events and events[-1].route == f"{API}/articles" and events[-1].status == 200
    assert events[-1].duration_ms >= 0
    dumped = " ".join(str(r.__dict__) for r in events)
    assert "abc.def.ghi" not in dumped and "secret-looking-tag" not in dumped  # no headers, no query strings


async def test_health_and_metrics_are_not_logged_per_request(client, caplog):
    with caplog.at_level(logging.INFO):
        await client.get("/health")
        await client.get("/metrics")
    assert not [r for r in caplog.records if getattr(r, "event", None) == "http_request"]


async def test_publishing_logs_a_business_event(client, make_user, publish_article, caplog):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    with caplog.at_level(logging.INFO):
        article = await publish_article(editor, "Logged story")
    published = [r for r in caplog.records if getattr(r, "event", None) == "article_publish"]
    assert published and published[-1].article_id == article["id"]


# -- metrics ---------------------------------------------------------------------------------------------


async def _metrics(client) -> str:
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    return resp.text


async def test_http_metrics_use_route_templates_not_raw_urls(client, make_user, publish_article):
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    article = await publish_article(editor, "Metric subject")
    await client.get(f"{API}/articles/{article['slug']}")
    await client.get(f"{API}/articles/does-not-exist")
    text = await _metrics(client)
    assert 'http_requests_total{method="GET",route="/api/v1/articles/{slug}",status="200"}' in text
    assert 'route="/api/v1/articles/{slug}",status="404"' in text
    assert article["slug"] not in text  # a million slugs would be a million series
    assert "http_request_duration_seconds_bucket" in text


async def test_unknown_urls_all_share_one_series(client):
    for i in range(5):
        await client.get(f"/random-probe-{i}/wp-admin")
    text = await _metrics(client)
    assert 'route="unmatched"' in text and "random-probe" not in text


def test_route_template():
    from app.main import route_template

    scope = {"endpoint": object(), "path": "/api/v1/teams/7/news", "path_params": {"team_id": 7}}
    assert route_template(scope) == "/api/v1/teams/{team_id}/news"
    assert route_template({"endpoint": object(), "path": "/health", "path_params": {}}) == "/health"
    assert route_template({"path": "/anything"}) == "unmatched"


async def test_search_metrics(client):
    await client.get(f"{API}/search", params={"q": "Arsenal"})
    await client.get(f"{API}/search", params={"q": "zzzz-nothing"})
    await client.get(f"{API}/search/suggestions", params={"q": "ars"})
    text = await _metrics(client)
    assert 'search_requests_total{kind="unified"}' in text and 'search_requests_total{kind="suggestions"}' in text
    assert "search_empty_results_total" in text
    assert 'search_duration_seconds_count{kind="unified"}' in text


async def test_business_counters_move_and_are_exposed_per_role(client, make_user, upload, publish_article):
    from app.services.metrics import metrics

    before = dict(metrics.snapshot())
    _, editor = await make_user("ed@example.com", UserRole.EDITOR)
    _, fan = await make_user("fan@example.com")
    assert (await upload(editor)).status_code == 201
    assert (await upload(editor, data=b"garbage")).status_code == 422
    article = await publish_article(editor, "Counted")
    await client.post(f"{API}/comments", json={"target_type": "article", "target_id": article["id"], "body": "Hi"}, headers=fan)
    await client.put(f"{API}/reactions/article/{article['id']}", json={"kind": "fire"}, headers=fan)
    poll = (await client.post(f"{API}/editor/polls", json={"question": "Count this poll?", "options": ["Yes", "No"]}, headers=editor)).json()
    await client.post(f"{API}/polls/{poll['id']}/vote", json={"option_id": poll["options"][0]["id"]}, headers=fan)
    after = metrics.snapshot()
    for name in (
        "media_uploads_total", "media_uploads_rejected_total", "articles_published_total",
        "comments_created_total", "reactions_total", "poll_votes_total",
    ):
        assert after[name] == before[name] + 1, name


async def test_the_celery_queue_length_is_exposed(client, fake_redis):
    from app.services.metrics import metrics

    metrics.cache_hit()
    metrics.flush()  # make sure at least one aggregated series exists
    await fake_redis.raw.hset("football:metrics:counters:api", mapping={"cache_hits_total": 1})
    await fake_redis.raw.rpush("football", "task-1", "task-2", "task-3")
    assert 'celery_queue_length{queue="football"} 3.0' in await _metrics(client)


def test_celery_signals_count_tasks_and_failures():
    from app.services.metrics import metrics
    from app.worker import celery_app as module

    before = metrics.snapshot()
    module._on_task_postrun()
    module._on_task_failure(task_id="t-1", exception=RuntimeError("x"), sender=type("T", (), {"name": "app.worker.tasks.sync"})())
    after = metrics.snapshot()
    assert after["celery_tasks_total"] == before["celery_tasks_total"] + 2
    assert after["celery_task_failures_total"] == before["celery_task_failures_total"] + 1


def test_prometheus_and_grafana_configuration_is_valid():
    """The shipped monitoring config parses and the dashboards only query metrics the API exposes."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[3] / "monitoring"
    if not root.exists():
        pytest.skip("monitoring/ not present")
    import yaml  # type: ignore[import-untyped]

    prom = yaml.safe_load((root / "prometheus" / "prometheus.yml").read_text(encoding="utf-8"))
    jobs = {j["job_name"] for j in prom["scrape_configs"]}
    assert {"api", "redis"} <= jobs
    dashboards = list((root / "grafana" / "dashboards").glob("*.json"))
    assert len(dashboards) >= 3
    known = {
        "http_requests_total", "http_request_duration_seconds_bucket", "search_requests_total", "search_duration_seconds_bucket",
        "search_empty_results_total", "celery_queue_length", "celery_tasks_total", "celery_task_failures_total",
        "websocket_connections", "websocket_messages_sent_total", "notifications_sent_total", "notifications_failed_total",
        "notifications_deduplicated_total", "cache_hits_total", "cache_misses_total", "live_matches", "media_uploads_total",
        "media_uploads_rejected_total", "articles_published_total", "scheduled_publish_total", "comments_created_total",
        "comments_reported_total", "reactions_total", "poll_votes_total", "sync_jobs_total", "sync_jobs_failed_total",
        "provider_requests_total", "provider_errors_total", "websocket_connections_opened_total", "websocket_disconnections_total",
        "analytics_generation_total", "analytics_generation_failures_total", "prediction_generation_total",
        "prediction_evaluation_total", "insight_generation_total", "subscription_created_total", "subscription_renewed_total",
        "subscription_cancelled_total", "subscription_payment_failed_total", "payment_webhooks_total",
        "payment_webhooks_rejected_total", "premium_feature_usage_total", "premium_feature_denied_total",
        "up",
    }
    for path in dashboards:
        board = json.loads(path.read_text(encoding="utf-8"))
        assert board["title"] and board["panels"]
        for panel in board["panels"]:
            for target in panel.get("targets", []):
                names = set(re.findall(r"[a-zA-Z_:][a-zA-Z0-9_:]*", re.sub(r'"[^"]*"|\{[^}]*\}|\[[^\]]*\]', "", target["expr"])))
                metric_names = {n for n in names if n.endswith(("_total", "_bucket", "_length", "_connections", "_matches")) or n in known}
                unknown = {n for n in metric_names if n not in known and not n.startswith("redis_")}
                assert not unknown, f"{path.name}: {panel['title']} queries unknown metric(s) {unknown}"
