"""The owner's requirements for error monitoring, as tests."""
import kit

EVENT = {"platform": "python", "exception": {"values": [{"type": "ValueError", "stacktrace": {"frames": [{"function": "checkout"}]}}]}}


def test_sentry_sdk_events():
    assert kit.start().ingest(EVENT)


def test_issue_grouping():
    s = kit.start()
    assert s.ingest(EVENT) == s.ingest(EVENT) and len(s.issues) == 1


def test_alert_rules():
    s = kit.start()
    s.ingest(EVENT)
    s.ingest(EVENT)
    assert len(s.alerts) == 1


def test_performance_tracing():
    assert kit.start().trace({"name": "GET /checkout", "duration_ms": 120})
