"""
Budget stores: spend shared by several workers and kept across restarts.

The Redis cases run against a small in-process fake of the five commands
RedisBudgetStore uses. Set LUMEN_TEST_REDIS_URL (e.g. redis://localhost:6379/15)
to also run them against a real server; that database is flushed.
"""
import os
import sys
import threading

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

import pytest
from lumen_ai import BudgetExporter, MemoryBudgetStore, RedisBudgetStore

REDIS_URL = os.environ.get("LUMEN_TEST_REDIS_URL")


class _FakeRedis:
    """HINCRBYFLOAT, HINCRBY, HGET, EXPIRE and SET NX EX, atomic like Redis."""

    def __init__(self):
        self._lock = threading.Lock()
        self.hashes = {}
        self.strings = {}
        self.ttls = {}

    def hincrbyfloat(self, key, field, amount):
        with self._lock:
            row = self.hashes.setdefault(key, {})
            row[field] = float(row.get(field, 0.0)) + float(amount)
            return row[field]

    def hincrby(self, key, field, amount):
        with self._lock:
            row = self.hashes.setdefault(key, {})
            row[field] = int(row.get(field, 0)) + int(amount)
            return row[field]

    def hget(self, key, field):
        value = self.hashes.get(key, {}).get(field)
        return None if value is None else str(value).encode()

    def expire(self, key, seconds):
        self.ttls[key] = seconds
        return True

    def set(self, key, value, nx=False, ex=None):
        with self._lock:
            if nx and key in self.strings:
                return None
            self.strings[key] = value
            self.ttls[key] = ex
            return True


@pytest.fixture(params=["fake", "real"])
def client(request):
    if request.param == "fake":
        yield _FakeRedis()
        return
    if not REDIS_URL:
        pytest.skip("set LUMEN_TEST_REDIS_URL to run against a real Redis")
    import redis
    real = redis.Redis.from_url(REDIS_URL)
    real.flushdb()
    yield real
    real.flushdb()


class _Capture:
    def __init__(self):
        self.events = []

    def export(self, tenant_id, event):
        self.events.append(event)

    def shutdown(self):
        pass


def _event(cost, timestamp="2026-10-28T12:00:00+00:00", unpriced=False):
    return {"cost_usd": cost, "timestamp": timestamp, "unpriced": unpriced,
            "event_type": "LLM_CALL_COMPLETED", "trace_id": "t", "span_id": "s"}


def _alerts(*captures):
    return [e for c in captures for e in c.events if e["event_type"] == "COST_THRESHOLD_EXCEEDED"]


def _worker(store, capture, alerts):
    return BudgetExporter(capture, {"acme": 10.0}, store=store, on_alert=alerts.append)


def test_two_workers_add_to_one_total_and_alert_once(client):
    store, alerts = RedisBudgetStore(client), []
    first, second = _Capture(), _Capture()
    a, b = _worker(store, first, alerts), _worker(store, second, alerts)

    a.export("acme", _event(5.0))
    b.export("acme", _event(3.5))  # 8.5 of 10: the 80% alert, from worker b
    a.export("acme", _event(1.0))
    b.export("acme", _event(0.5))  # 10.0: the 100% alert

    assert [x.threshold for x in alerts] == [0.8, 1.0]
    assert [x.spent_usd for x in alerts] == [8.5, 10.0]
    assert len(_alerts(first, second)) == 2
    assert a.spent("acme") == b.spent("acme") == pytest.approx(10.0)


def test_spend_survives_a_restart(client):
    store, alerts = RedisBudgetStore(client), []
    _worker(store, _Capture(), alerts).export("acme", _event(7.0))
    restarted = _worker(RedisBudgetStore(client), _Capture(), alerts)
    restarted.export("acme", _event(1.0))

    assert restarted.spent("acme") == pytest.approx(8.0)
    assert [x.threshold for x in alerts] == [0.8]


def test_concurrent_workers_lose_no_spend_and_alert_once(client):
    store, alerts = RedisBudgetStore(client), []
    workers = [_worker(store, _Capture(), alerts) for _ in range(8)]

    def run(worker):
        for _ in range(50):
            worker.export("acme", _event(0.03))

    threads = [threading.Thread(target=run, args=(w,)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert store.spent("acme", "2026-10") == pytest.approx(12.0)  # 400 * 0.03
    assert sorted(x.threshold for x in alerts) == [0.8, 1.0]


def test_periods_and_tenants_are_separate_keys(client):
    store = RedisBudgetStore(client, prefix="t")
    exporter = BudgetExporter(_Capture(), default_limit=10.0, store=store)
    exporter.export("acme", _event(2.0))
    exporter.export("acme", _event(3.0, timestamp="2026-11-01T00:00:00+00:00"))
    exporter.export("globex", _event(4.0))

    assert store.spent("acme", "2026-10") == pytest.approx(2.0)
    assert store.spent("acme", "2026-11") == pytest.approx(3.0)
    assert store.spent("globex", "2026-10") == pytest.approx(4.0)
    assert exporter.spent("acme") == pytest.approx(3.0)  # latest period seen


def test_unpriced_events_are_counted_across_workers(client):
    store, alerts = RedisBudgetStore(client), []
    _worker(store, _Capture(), alerts).export("acme", _event(0.0, unpriced=True))
    _worker(store, _Capture(), alerts).export("acme", _event(9.0))

    assert alerts[0].unpriced_events == 1


def test_keys_expire():
    fake = _FakeRedis()
    store = RedisBudgetStore(fake, prefix="p", ttl_seconds=3600)
    BudgetExporter(_Capture(), {"acme": 1.0}, store=store).export("acme", _event(1.0))

    assert fake.ttls == {"p:acme:2026-10": 3600, "p:acme:2026-10:alert:0.8": 3600,
                         "p:acme:2026-10:alert:1": 3600}


def test_a_failing_store_never_breaks_export(caplog):
    class _Down:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise ConnectionError("redis is down")
            return fail

    capture = _Capture()
    exporter = BudgetExporter(capture, {"acme": 1.0}, store=RedisBudgetStore(_Down()))
    exporter.export("acme", _event(5.0))

    assert len(capture.events) == 1 and not _alerts(capture)
    assert "could not update the budget store" in caplog.text


def test_memory_store_is_the_default_and_stays_per_process():
    alerts = []
    a = BudgetExporter(_Capture(), {"acme": 10.0}, on_alert=alerts.append)
    b = BudgetExporter(_Capture(), {"acme": 10.0}, on_alert=alerts.append)
    a.export("acme", _event(5.0))
    b.export("acme", _event(5.0))

    assert a.spent("acme") == b.spent("acme") == 5.0
    assert alerts == []
    assert isinstance(a._store, MemoryBudgetStore)


def test_bad_ttl_is_rejected():
    with pytest.raises(ValueError):
        RedisBudgetStore(_FakeRedis(), ttl_seconds=0)
