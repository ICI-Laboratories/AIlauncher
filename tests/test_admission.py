import asyncio

import pytest

from lmserv.server.admission import AdmissionController, AdmissionQueueFull, AdmissionTimeout


async def wait_queued(controller, count):
    async with asyncio.timeout(1):
        while controller.snapshot()["queued"] != count:
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_bounds_and_context_holds_capacity_until_exit():
    controller = AdmissionController(max_inflight=1, per_app_inflight=1, max_queue=1)
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def request():
        async with controller.acquire("second", "vision") as lease:
            assert lease.app_id == "second"
            assert lease.workload == "vision"
            entered.set()
            await finish.wait()

    async with controller.acquire("first"):
        task = asyncio.create_task(request())
        await wait_queued(controller, 1)
        assert not entered.is_set()
        with pytest.raises(AdmissionQueueFull):
            async with controller.acquire("third"):
                pytest.fail("full queue admitted request")
    await entered.wait()
    assert controller.snapshot()["inflight"] == 1
    assert controller.snapshot()["workloads"] == {"vision": 1}
    finish.set()
    await task
    assert controller.snapshot()["inflight"] == 0
    assert controller.snapshot()["totals"]["rejected"] == 1


@pytest.mark.asyncio
async def test_round_robin_does_not_let_busy_app_monopolize_queue():
    controller = AdmissionController(max_inflight=1, per_app_inflight=1)
    order = []

    async def request(app, number):
        async with controller.acquire(app):
            order.append((app, number))
            await asyncio.sleep(0)

    async with controller.acquire("holder"):
        tasks = [asyncio.create_task(request("a", n)) for n in range(3)]
        await wait_queued(controller, 3)
        tasks += [asyncio.create_task(request("b", n)) for n in range(2)]
        await wait_queued(controller, 5)
    await asyncio.gather(*tasks)
    assert order == [("a", 0), ("b", 0), ("a", 1), ("b", 1), ("a", 2)]
    assert controller.snapshot()["apps"] == {}


@pytest.mark.asyncio
async def test_per_app_limit_does_not_block_other_app():
    controller = AdmissionController(max_inflight=2, per_app_inflight=1)

    async def waiting():
        async with controller.acquire("a"):
            pass

    async with controller.acquire("a"):
        task = asyncio.create_task(waiting())
        await wait_queued(controller, 1)
        async with controller.acquire("b"):
            snapshot = controller.snapshot()
            assert snapshot["inflight"] == 2
            assert snapshot["queued"] == 1
            assert snapshot["apps"]["a"] == {"inflight": 1, "queued": 1}
    await task


@pytest.mark.asyncio
async def test_timeout_removes_waiter_and_recovers_capacity():
    controller = AdmissionController(max_inflight=1, queue_timeout=0.01)
    async with controller.acquire("a"):
        with pytest.raises(AdmissionTimeout):
            async with controller.acquire("b"):
                pytest.fail("must time out")
        assert controller.snapshot()["queued"] == 0
        assert "b" not in controller.snapshot()["apps"]
    async with controller.acquire("b"):
        assert controller.snapshot()["inflight"] == 1
    assert controller.snapshot()["totals"]["timed_out"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("grant_first", [False, True])
async def test_cancel_waiter_or_race_with_grant_never_leaks_capacity(grant_first):
    controller = AdmissionController(max_inflight=1, max_queue=1)
    holder = controller.acquire("holder")
    await holder.__aenter__()

    async def request():
        async with controller.acquire("cancelled"):
            await asyncio.Future()

    task = asyncio.create_task(request())
    await wait_queued(controller, 1)
    if grant_first:
        await holder.__aexit__(None, None, None)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    if not grant_first:
        await holder.__aexit__(None, None, None)
    assert controller.snapshot()["inflight"] == 0
    assert controller.snapshot()["queued"] == 0
    async with controller.acquire("healthy"):
        pass


@pytest.mark.asyncio
async def test_cancellation_and_backend_failure_release_active_lease():
    controller = AdmissionController(max_inflight=1)
    started = asyncio.Event()

    async def stream():
        async with controller.acquire("a"):
            started.set()
            await asyncio.Future()

    task = asyncio.create_task(stream())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(RuntimeError):
        async with controller.acquire("b"):
            raise RuntimeError("backend failed")
    assert controller.snapshot()["inflight"] == 0
    assert controller.snapshot()["totals"]["cancelled"] == 1


@pytest.mark.asyncio
async def test_no_waiting_queue_can_still_admit_immediate_request():
    controller = AdmissionController(max_inflight=1, max_queue=0)
    async with controller.acquire("a"):
        with pytest.raises(AdmissionQueueFull):
            async with controller.acquire("b"):
                pass
    assert controller.snapshot()["queued"] == 0


@pytest.mark.parametrize("kwargs", [
    {"max_inflight": 0}, {"max_queue": -1}, {"per_app_inflight": 0},
    {"queue_timeout": 0}, {"queue_timeout": float("nan")},
    {"queue_timeout": float("inf")}, {"max_inflight": 1.5},
])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        AdmissionController(**kwargs)
