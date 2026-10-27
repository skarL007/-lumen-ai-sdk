"""
AsyncRedisExporter behavior tests (no live Redis — _write_batch is stubbed).

Pins the contract that the old implementation violated:
  * export() must never deadlock on auto-flush (it re-acquired its own
    non-reentrant Lock via _flush_sync -> _drain_buffer).
  * aflush() and shutdown() must actually run the flush coroutine (the old
    code fire-and-forgot it when a loop was present, losing events).
  * the redis client is loop-bound, so all I/O must run on ONE owned loop,
    not throwaway asyncio.run() loops.
"""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src")
)

from lumen_ai.providers import AsyncRedisExporter


def _recorder():
    recorded = []
    done = threading.Event()

    async def rec(events):
        recorded.append(list(events))
        done.set()

    return rec, recorded, done


def test_autoflush_does_not_deadlock():
    exp = AsyncRedisExporter("redis://localhost:6379/0", max_buffer=2)
    rec, recorded, done = _recorder()
    exp._write_batch = rec

    def worker():
        exp.export("t", {"id": "1"})
        exp.export("t", {"id": "2"})  # crosses max_buffer -> auto-flush

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(timeout=3)
    try:
        assert not th.is_alive(), "export() deadlocked on auto-flush"
        assert done.wait(timeout=3), "auto-flush coroutine never ran"
        assert recorded == [[("t", {"id": "1"}), ("t", {"id": "2"})]]
    finally:
        exp.shutdown()


def test_aflush_runs_and_awaits_the_flush():
    exp = AsyncRedisExporter("redis://localhost:6379/0", max_buffer=100)
    rec, recorded, done = _recorder()
    exp._write_batch = rec

    exp.export("acme", {"id": "a"})

    async def drive():
        await exp.aflush()

    asyncio.run(drive())
    assert recorded == [[("acme", {"id": "a"})]]
    exp.shutdown()


def test_shutdown_flushes_remaining_and_stops_thread():
    exp = AsyncRedisExporter("redis://localhost:6379/0", max_buffer=100)
    rec, recorded, done = _recorder()
    exp._write_batch = rec

    exp.export("acme", {"id": "z"})
    exp.shutdown()

    assert recorded == [[("acme", {"id": "z"})]]
    assert not exp._thread.is_alive()


def test_shutdown_waits_for_in_flight_autoflush():
    exp = AsyncRedisExporter("redis://localhost:6379/0", max_buffer=1)
    recorded = []

    async def slow_write(events):
        await asyncio.sleep(0.05)
        recorded.append(list(events))

    exp._write_batch = slow_write
    exp.export("acme", {"id": "slow"})
    exp.shutdown()

    assert recorded == [[("acme", {"id": "slow"})]]
    assert not exp._thread.is_alive()


def test_autoflush_future_is_registered_before_shutdown_snapshot():
    class RaceExporter(AsyncRedisExporter):
        def __init__(self):
            super().__init__("redis://localhost:6379/0", max_buffer=1)
            self.schedule_entered = threading.Event()
            self.release_schedule = threading.Event()
            self.lock_was_held = []

        def _schedule_locked(self, coro):
            self.lock_was_held.append(self._lock._is_owned())
            self.schedule_entered.set()
            assert self.release_schedule.wait(timeout=3), "schedule was not released"
            return super()._schedule_locked(coro)

    exp = RaceExporter()
    recorded = []

    async def slow_write(events):
        await asyncio.sleep(0.01)
        recorded.append(list(events))

    exp._write_batch = slow_write

    worker = threading.Thread(
        target=lambda: exp.export("acme", {"id": "race"}), daemon=True
    )
    worker.start()
    assert exp.schedule_entered.wait(timeout=3), "auto-flush was not scheduled"

    shutdown_thread = threading.Thread(target=exp.shutdown, daemon=True)
    shutdown_thread.start()
    time.sleep(0.05)
    assert shutdown_thread.is_alive(), "shutdown raced past auto-flush registration"

    exp.release_schedule.set()
    worker.join(timeout=3)
    shutdown_thread.join(timeout=3)

    assert not worker.is_alive()
    assert not shutdown_thread.is_alive()
    assert exp.lock_was_held == [True]
    assert recorded == [[("acme", {"id": "race"})]]
    assert not exp._thread.is_alive()


def test_shutdown_is_idempotent():
    exp = AsyncRedisExporter("redis://localhost:6379/0", max_buffer=100)

    async def noop(events):
        return None

    exp._write_batch = noop
    exp.shutdown()
    exp.shutdown()  # must not raise
