"""Bounded, fair admission for a shared inference engine.

One controller belongs to one asyncio event loop/process. Hold ``acquire`` for
an entire response, including streaming: releasing on response headers would
allow the backend to exceed its concurrency budget.
"""

from __future__ import annotations

import asyncio
import math
from collections import Counter, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import AsyncIterator


class AdmissionQueueFull(Exception):
    """The bounded waiting queue cannot accept another request."""


class AdmissionTimeout(Exception):
    """The request did not receive a slot before its queue deadline."""


@dataclass(frozen=True)
class AdmissionLease:
    app_id: str
    workload: str
    queued_seconds: float


@dataclass(eq=False)
class _Waiter:
    app_id: str
    workload: str
    future: asyncio.Future[AdmissionLease]
    created: float
    granted: bool = False


class AdmissionController:
    """FIFO within each app, round-robin across apps that have capacity.

    Queue capacity counts waiting requests, not running requests. Workload is
    metadata only: text and vision share the same engine capacity. This class
    stores identifiers and counters, never prompts or response content.
    """

    def __init__(
        self,
        max_inflight: int = 4,
        max_queue: int = 32,
        per_app_inflight: int = 2,
        queue_timeout: float = 60.0,
    ) -> None:
        for name, value, minimum in (
            ("max_inflight", max_inflight, 1),
            ("max_queue", max_queue, 0),
            ("per_app_inflight", per_app_inflight, 1),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if not math.isfinite(queue_timeout) or queue_timeout <= 0:
            raise ValueError("queue_timeout must be finite and positive")
        self.max_inflight = max_inflight
        self.max_queue = max_queue
        self.per_app_inflight = per_app_inflight
        self.queue_timeout = queue_timeout
        self._queues: dict[str, deque[_Waiter]] = {}
        self._round_robin: deque[str] = deque()
        self._active: Counter[str] = Counter()
        self._workloads: Counter[str] = Counter()
        self._inflight = 0
        self._queued = 0
        self._totals: Counter[str] = Counter(
            admitted=0, completed=0, rejected=0, timed_out=0, cancelled=0
        )

    def _dispatch(self) -> None:
        # Each pass considers every waiting app once; capped apps cannot block
        # other apps. No await inside state changes: cancellation is atomic here.
        while self._inflight < self.max_inflight and self._round_robin:
            granted = False
            for _ in range(len(self._round_robin)):
                app_id = self._round_robin.popleft()
                queue = self._queues[app_id]
                if self._active[app_id] >= self.per_app_inflight:
                    self._round_robin.append(app_id)
                    continue
                waiter = queue.popleft()
                if queue:
                    self._round_robin.append(app_id)
                else:
                    del self._queues[app_id]
                self._queued -= 1
                self._inflight += 1
                self._active[app_id] += 1
                self._workloads[waiter.workload] += 1
                self._totals["admitted"] += 1
                waiter.granted = True
                waiter.future.set_result(
                    AdmissionLease(app_id, waiter.workload, monotonic() - waiter.created)
                )
                granted = True
                break
            if not granted:
                break

    def _release(self, waiter: _Waiter) -> None:
        self._inflight -= 1
        self._active[waiter.app_id] -= 1
        self._workloads[waiter.workload] -= 1
        if not self._active[waiter.app_id]:
            del self._active[waiter.app_id]
        if not self._workloads[waiter.workload]:
            del self._workloads[waiter.workload]
        self._totals["completed"] += 1
        self._dispatch()

    def _abandon(self, waiter: _Waiter) -> None:
        # A grant can race with timeout/cancellation. Return its slot even if
        # the caller never observed the successfully completed future.
        if waiter.granted:
            self._release(waiter)
            return
        queue = self._queues[waiter.app_id]
        queue.remove(waiter)
        self._queued -= 1
        if not queue:
            del self._queues[waiter.app_id]
            self._round_robin.remove(waiter.app_id)
        waiter.future.cancel()
        self._dispatch()

    @asynccontextmanager
    async def acquire(
        self, app_id: str, workload: str = "text"
    ) -> AsyncIterator[AdmissionLease]:
        if not app_id:
            raise ValueError("app_id is required")
        if workload not in {"text", "vision"}:
            raise ValueError("workload must be text or vision")
        can_start = (
            self._inflight < self.max_inflight
            and self._active[app_id] < self.per_app_inflight
        )
        if self._queued >= self.max_queue and not can_start:
            self._totals["rejected"] += 1
            raise AdmissionQueueFull("Inference queue is full")
        waiter = _Waiter(app_id, workload, asyncio.get_running_loop().create_future(), monotonic())
        if app_id not in self._queues:
            self._queues[app_id] = deque()
            self._round_robin.append(app_id)
        self._queues[app_id].append(waiter)
        self._queued += 1
        self._dispatch()
        try:
            # Shield the future so dispatch cannot set_result on a future
            # cancelled by wait_for; explicit cleanup owns all state changes.
            lease = await asyncio.wait_for(asyncio.shield(waiter.future), self.queue_timeout)
        except asyncio.TimeoutError as exc:
            self._totals["timed_out"] += 1
            self._abandon(waiter)
            raise AdmissionTimeout("Timed out waiting for inference capacity") from exc
        except asyncio.CancelledError:
            self._totals["cancelled"] += 1
            self._abandon(waiter)
            raise
        try:
            yield lease
        except asyncio.CancelledError:
            self._totals["cancelled"] += 1
            raise
        finally:
            self._release(waiter)

    def snapshot(self) -> dict:
        """Return current occupancy and lifetime counters without request data."""
        apps = self._active.keys() | self._queues.keys()
        return {
            "max_inflight": self.max_inflight,
            "max_queue": self.max_queue,
            "per_app_inflight": self.per_app_inflight,
            "inflight": self._inflight,
            "queued": self._queued,
            "workloads": dict(self._workloads),
            "apps": {
                app: {"inflight": self._active[app], "queued": len(self._queues.get(app, ())) }
                for app in sorted(apps)
            },
            "totals": dict(self._totals),
        }
