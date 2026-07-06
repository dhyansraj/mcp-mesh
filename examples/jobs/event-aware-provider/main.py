#!/usr/bin/env python3
"""
MeshJob Phase 2 — Producer Example: event-aware long task (v2.2 event injection).

Demonstrates the producer-side event-channel surface added in v2.2:

    @mesh.tool(capability="event_aware_long_task", task=True)
    async def event_aware_long_task(..., controller: MeshJob = None):
        while True:
            event = await controller.recv_event(
                types=["work", "stop"], timeout_secs=30.0,
            )
            ...

Pattern: the handler drains a per-job event log inline. ``recv_event``
long-polls the registry; each invocation returns the next event matching
``types``, or ``None`` if no event arrives within ``timeout_secs``. The
``stop`` event lets a remote caller cleanly shut the loop down without
having to ``cancel()`` the job.

Pair this provider with ``../event-aware-consumer/main.py`` for a full
3-terminal demo: registry → provider → consumer drives 3 ``work`` events
+ 1 ``stop``, subscribes via ``mesh.jobs.subscribe_events`` to mirror
the same stream, then awaits the job's terminal result.

Run:
    MCP_MESH_REGISTRY_URL=http://localhost:8000 python3 main.py
"""

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Event-Aware Provider")


@app.tool()
@mesh.tool(
    capability="event_aware_long_task",
    task=True,
    description=(
        "Long-running task that drains injected events. Loops on "
        "recv_event(types=['work', 'stop']) and exits cleanly on 'stop'."
    ),
)
async def event_aware_long_task(controller: MeshJob = None) -> dict:
    """Process injected ``work`` events until a ``stop`` event arrives.

    The handler parks on ``recv_event`` between events — the long-poll
    is registry-backed, so this scales to minutes of idle time without
    burning CPU. Progress updates flush after each ``work`` event so a
    consumer polling status sees the counter advance in real time.
    """
    if controller is None:
        return {"error": "no job controller injected"}

    processed = 0
    while True:
        event = await controller.recv_event(
            types=["work", "stop"], timeout_secs=30.0
        )
        if event is None:
            # Long-poll budget elapsed with no matching event. In a real
            # producer this is a good moment to tick housekeeping (refresh
            # leases, write checkpoints) before re-parking.
            await controller.update_progress(
                processed / (processed + 1),
                f"idle, waiting for events (processed={processed})",
            )
            continue

        if event["type"] == "stop":
            payload = {"processed": processed, "status": "stopped"}
            await controller.complete(payload)
            return payload

        # 'work' event — advance counter, log progress.
        processed += 1
        await controller.update_progress(
            min(processed / 10.0, 0.99),
            f"processed work item {processed} (seq={event['seq']})",
        )


@app.tool()
@mesh.tool(
    capability="resumable_event_task",
    task=True,
    resume_cursor=True,
    description=(
        "Durable variant of event_aware_long_task. Opts into "
        "resume_cursor so a re-claimed run resumes after the last "
        "processed event instead of replaying its event log from seq 0."
    ),
)
async def resumable_event_task(controller: MeshJob = None) -> dict:
    """Accumulate each ``work`` event's amount, exit cleanly on ``stop``.

    ``resume_cursor=True`` (issue #1277): if this job is re-claimed after a
    crash or reclaim, the handler resumes ``recv_event`` from the persisted
    per-filter cursor — it does NOT replay the event log from seq 0, so the
    non-idempotent ``total += amount`` accumulation below is not re-applied
    for events already consumed on the prior claim.

    Resume contract:
      * At-least-once still holds: a bounded tail of already-processed events
        may replay on resume, so keep per-event effects tolerant of a rare
        repeat (or fence on ``event['seq']``).
      * Consumption MUST stay strictly sequential-per-filter: process each
        event fully before calling ``recv_event`` again. Do NOT prefetch a
        batch or fan events out to concurrent workers — the persisted cursor
        only advances correctly for in-order, one-at-a-time draining.
    """
    if controller is None:
        return {"error": "no job controller injected"}

    total = 0
    processed = 0
    while True:
        event = await controller.recv_event(
            types=["work", "stop"], timeout_secs=30.0
        )
        if event is None:
            continue

        if event["type"] == "stop":
            payload = {
                "processed": processed,
                "total": total,
                "status": "stopped",
            }
            await controller.complete(payload)
            return payload

        # Sequential-per-filter: this non-idempotent accumulation runs once
        # per event, in order, before we request the next one. The persisted
        # cursor advances only because we never prefetch or spawn here.
        amount = (event.get("payload") or {}).get("amount", 1)
        total += amount
        processed += 1
        await controller.update_progress(
            min(processed / 10.0, 0.99),
            f"applied work item {processed} "
            f"(seq={event['seq']}, total={total})",
        )


@mesh.agent(
    name="event-aware-provider",
    version="1.0.0",
    description=(
        "MeshJob v2.2 producer — drains injected events via recv_event."
    ),
    http_port=9102,
    enable_http=True,
    auto_run=True,
)
class EventAwareProvider:
    """Hosts the ``event_aware_long_task`` capability as a task=True tool."""

    pass
