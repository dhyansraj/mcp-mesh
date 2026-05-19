#!/usr/bin/env python3
"""
MeshJob Phase 2 — Consumer Example: drive an event-aware job (v2.2).

Demonstrates the three v2.2 event-channel surfaces from outside the
running handler:

    proxy = await event_aware_long_task.submit(...)
    asyncio.create_task(_subscribe(proxy.job_id))   # observer
    await mesh.jobs.post_event(proxy.job_id, "work", {...})  # producer-to-producer
    await proxy.wait(...)                             # terminal result

The subscriber and the poster run concurrently. Each has its own cursor:
the in-handler ``recv_event`` cursor on the producer side is independent
from the observer's ``subscribe_events`` cursor — both observe every
``work`` event the consumer posts.

Pair this consumer with ``../event-aware-provider/main.py``. Run after
the provider is up:

    MCP_MESH_REGISTRY_URL=http://localhost:8000 python3 main.py
"""

import asyncio
import logging

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

log = logging.getLogger("event-aware-consumer")
app = FastMCP("Event-Aware Consumer")


@app.tool()
@mesh.tool(
    capability="drive_event_aware_task",
    # Dep name must match the MeshJob param name so DI wires the slot
    # as a MeshJobSubmitter (not a regular McpMeshTool proxy).
    dependencies=["event_aware_long_task"],
    description=(
        "Submit an event-aware job, post 3 'work' events + 1 'stop', "
        "mirror the stream via subscribe_events, and return both halves."
    ),
)
async def drive_event_aware_task(
    event_aware_long_task: MeshJob = None,
) -> dict:
    """End-to-end driver: submit, observe, post, await."""
    if event_aware_long_task is None:
        return {"error": "event_aware_long_task submitter not injected"}

    proxy = await event_aware_long_task.submit(max_duration=60)
    job_id = proxy.job_id

    # Brief wait so the producer claims the job + parks on recv_event
    # before the first event lands. Without this the event would still
    # be observable (the registry log is append-only), but we wouldn't
    # be exercising the long-poll wake path.
    await asyncio.sleep(2.0)

    observed: list[dict] = []

    async def _subscribe() -> None:
        """Mirror the job's 'work' event stream into ``observed``."""
        async for event in mesh.jobs.subscribe_events(
            job_id, types=["work"], long_poll_secs=5.0
        ):
            log.info("subscribed event seq=%s payload=%s", event["seq"], event["payload"])
            observed.append({"seq": event["seq"], "payload": event["payload"]})
            if len(observed) >= 3:
                return

    subscriber = asyncio.create_task(_subscribe())

    posted_seqs: list[int] = []
    for i in range(1, 4):
        await asyncio.sleep(0.5)
        receipt = await mesh.jobs.post_event(job_id, "work", {"item": i})
        posted_seqs.append(receipt["seq"])
        log.info("posted work item=%d seq=%d", i, receipt["seq"])

    # Tell the handler to wind down.
    await mesh.jobs.post_event(job_id, "stop", {})
    log.info("posted stop")

    # Bound the subscriber wait so a stuck observer doesn't hang the
    # whole tool call.
    try:
        await asyncio.wait_for(subscriber, timeout=15.0)
    except asyncio.TimeoutError:
        # Drain the cancelled task so asyncio doesn't emit "Task was destroyed but it is pending!" on shutdown.
        subscriber.cancel()
        try:
            await subscriber
        except asyncio.CancelledError:
            pass

    result = await proxy.wait(timeout_secs=30)
    return {
        "job_id": job_id,
        "posted_seqs": posted_seqs,
        "observed_count": len(observed),
        "observed_events": observed,
        "result": result,
    }


@mesh.agent(
    name="event-aware-consumer",
    version="1.0.0",
    description=(
        "MeshJob v2.2 consumer — drives an event-aware job via "
        "post_event + subscribe_events."
    ),
    http_port=9103,
    enable_http=True,
    auto_run=True,
)
class EventAwareConsumer:
    """Hosts the ``drive_event_aware_task`` capability."""

    pass
