#!/usr/bin/env python3
"""MeshJob test-suite consumer (uc21).

Hosts several variants of the submit-and-await pattern so individual
test cases can exercise behavioural knobs without forking new agents:

- ``commission_report`` — submit + wait; raises on terminal error.
  Mirrors the upstream example.
- ``commission_with_options`` — submit + wait with caller-supplied
  ``max_retries`` and an optional ``total_deadline_secs`` (relative,
  converted to a UTC datetime under the hood). Returns a structured
  envelope on terminal failure instead of raising — lets tests assert
  status / error fields directly.
- ``commission_submit_only`` — submit and return ``{job_id}``
  immediately. Tests poll status / result / cancel themselves via
  the helper tools, which is the right shape for cancellation /
  recovery scenarios where blocking on ``wait()`` would hide signal.
- ``commission_explicit_fail`` — submits ``report_with_explicit_fail``
  with caller-supplied ``max_retries``. Always returns the structured
  envelope so tc05 can assert ``status=failed`` + attempt_count.
- ``commission_crash`` — submits ``report_that_crashes`` with caller-
  supplied ``max_retries`` and (optional) ``total_deadline_secs``.
- ``commission_overlong`` — submits ``runs_overlong``. Used by
  cancel-token tests.
- ``commission_downstream`` — submits ``report_with_downstream_call``.
  Used by tc09 to verify cancel aborts the downstream HTTP.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Long Task Consumer (uc21)")


def _utc_deadline_from_relative(secs: Optional[int]) -> Optional[datetime]:
    if secs is None:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=secs)


# ---------------------------------------------------------------------------
# Submit + wait (raises on terminal error) — happy-path baseline
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_report",
    dependencies=["generate_report"],
    description="Submit a generate_report job and wait up to 60s for the result.",
)
async def commission_report(
    user_id: str,
    sections: list[str],
    generate_report: MeshJob = None,
) -> dict:
    if generate_report is None:
        return {"error": "generate_report submitter not injected"}
    proxy = await generate_report.submit(
        user_id=user_id,
        sections=sections,
        max_duration=60,
    )
    return await proxy.wait(timeout_secs=60)


# ---------------------------------------------------------------------------
# Submit + wait with caller-controlled retry / deadline knobs
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_with_options",
    dependencies=["generate_report"],
    description="Submit generate_report with caller-supplied max_retries / total_deadline_secs.",
)
async def commission_with_options(
    user_id: str,
    sections: list[str],
    max_retries: int = 1,
    total_deadline_secs: Optional[int] = None,
    wait_timeout_secs: int = 60,
    generate_report: MeshJob = None,
) -> dict:
    if generate_report is None:
        return {"error": "generate_report submitter not injected"}
    proxy = await generate_report.submit(
        user_id=user_id,
        sections=sections,
        max_duration=60,
        max_retries=max_retries,
        total_deadline=_utc_deadline_from_relative(total_deadline_secs),
    )
    job_id = getattr(proxy, "job_id", None)
    try:
        result = await proxy.wait(timeout_secs=wait_timeout_secs)
        return {"job_id": job_id, "status": "completed", "result": result}
    except Exception as e:  # pragma: no cover - structured envelope for tests
        return {"job_id": job_id, "status": "wait_raised", "error": str(e)}


# ---------------------------------------------------------------------------
# Submit-only — return job_id immediately
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_submit_only",
    dependencies=["generate_report"],
    description="Submit generate_report and return the job_id without waiting.",
)
async def commission_submit_only(
    user_id: str,
    sections: list[str],
    max_retries: int = 1,
    max_duration: Optional[int] = None,
    generate_report: MeshJob = None,
) -> dict:
    if generate_report is None:
        return {"error": "generate_report submitter not injected"}
    # max_duration is Optional: when the caller omits it (None), we pass None
    # to submit() so the registry applies its DEFAULT lease (300s). This is
    # what the C2 stale-reaping test (tc28) needs — a job with NO explicit
    # max_duration whose effective stale ceiling is just
    # MCP_MESH_JOB_STALE_TIMEOUT, while the 300s default lease stays alive so
    # only the stale sweep (not the lease-reclaim sweep) can reap it. When a
    # caller DOES pass max_duration (e.g. tc30), it flows through verbatim and
    # raises the effective ceiling to max(stale_timeout, max_duration).
    proxy = await generate_report.submit(
        user_id=user_id,
        sections=sections,
        max_duration=max_duration,
        max_retries=max_retries,
    )
    return {"job_id": getattr(proxy, "job_id", None)}


# ---------------------------------------------------------------------------
# Explicit-fail submitter — submits report_with_explicit_fail
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_explicit_fail",
    dependencies=["report_with_explicit_fail"],
    description="Submit report_with_explicit_fail with caller-supplied max_retries.",
)
async def commission_explicit_fail(
    user_id: str,
    max_retries: int = 3,
    wait_timeout_secs: int = 30,
    report_with_explicit_fail: MeshJob = None,
) -> dict:
    if report_with_explicit_fail is None:
        return {"error": "report_with_explicit_fail submitter not injected"}
    proxy = await report_with_explicit_fail.submit(
        user_id=user_id,
        max_duration=30,
        max_retries=max_retries,
    )
    job_id = getattr(proxy, "job_id", None)
    try:
        result = await proxy.wait(timeout_secs=wait_timeout_secs)
        return {"job_id": job_id, "status": "completed", "result": result}
    except Exception as e:
        return {"job_id": job_id, "status": "wait_raised", "error": str(e)}


# ---------------------------------------------------------------------------
# Crash submitter — submits report_that_crashes
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_crash",
    dependencies=["report_that_crashes"],
    description="Submit report_that_crashes (always raises) with caller-supplied retry / deadline.",
)
async def commission_crash(
    user_id: str,
    max_retries: int = 0,
    total_deadline_secs: Optional[int] = None,
    report_that_crashes: MeshJob = None,
) -> dict:
    if report_that_crashes is None:
        return {"error": "report_that_crashes submitter not injected"}
    proxy = await report_that_crashes.submit(
        user_id=user_id,
        max_duration=30,
        max_retries=max_retries,
        total_deadline=_utc_deadline_from_relative(total_deadline_secs),
    )
    return {"job_id": getattr(proxy, "job_id", None)}


# ---------------------------------------------------------------------------
# Transient-failures submitter — submits report_with_transient_failures
# Used by tc23 to exercise @mesh.tool(retry_on=...) (#879).
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_transient_failures",
    dependencies=["report_with_transient_failures"],
    description="Submit report_with_transient_failures with caller-supplied max_retries.",
)
async def commission_transient_failures(
    user_id: str,
    max_retries: int = 3,
    transient_failures: int = 2,
    wait_timeout_secs: int = 30,
    report_with_transient_failures: MeshJob = None,
) -> dict:
    if report_with_transient_failures is None:
        return {"error": "report_with_transient_failures submitter not injected"}
    proxy = await report_with_transient_failures.submit(
        user_id=user_id,
        transient_failures=transient_failures,
        max_duration=30,
        max_retries=max_retries,
    )
    job_id = getattr(proxy, "job_id", None)
    try:
        result = await proxy.wait(timeout_secs=wait_timeout_secs)
        return {"job_id": job_id, "status": "completed", "result": result}
    except Exception as e:
        return {"job_id": job_id, "status": "wait_raised", "error": str(e)}


# ---------------------------------------------------------------------------
# Overlong submitter — submits runs_overlong (cancel-token tests)
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_overlong",
    dependencies=["runs_overlong"],
    description="Submit runs_overlong and return the job_id (no wait).",
)
async def commission_overlong(
    user_id: str,
    seconds: int = 30,
    runs_overlong: MeshJob = None,
) -> dict:
    if runs_overlong is None:
        return {"error": "runs_overlong submitter not injected"}
    proxy = await runs_overlong.submit(
        user_id=user_id,
        seconds=seconds,
        max_duration=120,
    )
    return {"job_id": getattr(proxy, "job_id", None)}


# ---------------------------------------------------------------------------
# Downstream-call submitter — submits report_with_downstream_call
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_downstream",
    dependencies=["report_with_downstream_call"],
    description="Submit report_with_downstream_call (provider calls slow_downstream) and return job_id.",
)
async def commission_downstream(
    user_id: str,
    report_with_downstream_call: MeshJob = None,
) -> dict:
    if report_with_downstream_call is None:
        return {"error": "report_with_downstream_call submitter not injected"}
    proxy = await report_with_downstream_call.submit(
        user_id=user_id,
        max_duration=120,
    )
    return {"job_id": getattr(proxy, "job_id", None)}


# ---------------------------------------------------------------------------
# Event-injection scenarios (tc24 / tc25 / tc26)
# ---------------------------------------------------------------------------
#
# Each capability submits one of the new ``task=True`` producers and
# drives ``mesh.jobs.post_event`` from inside the consumer's tool body
# to exercise the producer's ``recv_event`` long-poll. The Phase C
# helper ``mesh.jobs.post_event`` is the surface under test — it
# discovers the registry URL from ``MCP_MESH_REGISTRY_URL`` (set by
# the agent startup pipeline) and POSTs ``/jobs/{id}/events``.

import asyncio  # noqa: E402  (event-injection helpers below need asyncio.sleep)
import time  # noqa: E402  (claim-gate deadline in commission_cancel_via_event)


@app.tool()
@mesh.tool(
    capability="commission_event",
    dependencies=["run_with_event"],
    description="Submit run_with_event, sleep so producer parks on recv_event, then post one event.",
)
async def commission_event(
    run_with_event: MeshJob = None,
) -> dict:
    if run_with_event is None:
        return {"error": "run_with_event submitter not injected"}
    proxy = await run_with_event.submit(ctx={}, max_duration=60)
    # Brief wait so producer reaches recv_event before we post. Without
    # this, the post may land before the producer's claim worker has
    # even pulled the job off the queue — the event would still be
    # observable (the cursor is per-controller) but the test would
    # not exercise the long-poll wake path.
    await asyncio.sleep(2.0)
    receipt = await mesh.jobs.post_event(
        job_id=proxy.job_id,
        event_type="signal",
        payload={"hello": "world", "n": 42},
    )
    result = await proxy.wait(timeout_secs=30)
    return {
        "job_id": proxy.job_id,
        "post_seq": receipt["seq"],
        "job_result": result,
    }


@app.tool()
@mesh.tool(
    capability="commission_event_filter",
    dependencies=["run_with_filter"],
    description="Submit run_with_filter, post 2 ignored events, then the matching one.",
)
async def commission_event_filter(
    run_with_filter: MeshJob = None,
) -> dict:
    if run_with_filter is None:
        return {"error": "run_with_filter submitter not injected"}
    proxy = await run_with_filter.submit(ctx={}, max_duration=60)
    # Give the producer a moment to claim + park on recv_event.
    await asyncio.sleep(2.0)
    # Post 2 unrelated events — producer must NOT wake on these.
    r1 = await mesh.jobs.post_event(
        job_id=proxy.job_id,
        event_type="ignore_a",
        payload={"n": 1},
    )
    r2 = await mesh.jobs.post_event(
        job_id=proxy.job_id,
        event_type="ignore_b",
        payload={"n": 2},
    )
    # Brief gap so a buggy filter (one that DID wake on ignore_a) has
    # time to drive the producer to completion; if the producer is
    # already done by now, the matching post will get JobTerminalError.
    await asyncio.sleep(1.0)
    r3 = await mesh.jobs.post_event(
        job_id=proxy.job_id,
        event_type="target",
        payload={"got_it": True},
    )
    result = await proxy.wait(timeout_secs=30)
    return {
        "job_id": proxy.job_id,
        "ignore_seqs": [r1["seq"], r2["seq"]],
        "target_seq": r3["seq"],
        "result": result,
    }


@app.tool()
@mesh.tool(
    capability="commission_cancel_via_event",
    dependencies=["run_until_cancel"],
    description="Submit run_until_cancel, post a 'work' event, then cancel — synthetic 'cancelled' event must arrive.",
)
async def commission_cancel_via_event(
    run_until_cancel: MeshJob = None,
) -> dict:
    if run_until_cancel is None:
        return {"error": "run_until_cancel submitter not injected"}
    proxy = await run_until_cancel.submit(ctx={}, max_duration=60)
    # Deterministic claim gate (was a fixed 2s sleep): wait until a
    # producer replica has CLAIMED the job before posting 'work' and
    # cancelling below. Pull-mode rows are created with
    # owner_instance_id = NULL; the registry sets it on /jobs/claim.
    # The producer's idle claim poll backs off to a 5s cap, so the old
    # fixed 2s (+1s pre-cancel) budget could fire the cancel BEFORE the
    # claim — the producer then never ran run_until_cancel and the
    # synthetic 'cancelled' event went unobserved (issue #1207). Events
    # posted after the claim are safe: a fresh JobController's
    # recv_event replays from the first event in the job's event log.
    claim_deadline = time.monotonic() + 30.0
    while True:
        try:
            claim_status = await proxy.status()
        except Exception:
            # Transient status-read failures (registry hiccup) are
            # tolerated within the budget — keep polling.
            claim_status = None
        owner = (claim_status or {}).get("owner_instance_id")
        if owner:
            break
        if time.monotonic() >= claim_deadline:
            return {
                "error": "job never claimed within 30s — cannot exercise cancel-via-event",
                "job_id": proxy.job_id,
                "last_status": claim_status,
            }
        await asyncio.sleep(0.3)
    work_receipt = await mesh.jobs.post_event(
        job_id=proxy.job_id,
        event_type="work",
        payload={"item": 1},
    )
    # Give the producer a moment to consume the 'work' event before we
    # fire the cancel. This makes the two events strictly ordered in
    # the producer's events_seen list (work first, cancelled second).
    await asyncio.sleep(1.0)
    await proxy.cancel(reason="external_stop_requested")
    # The job is now cancelled — the producer's recv_event loop will
    # observe the synthetic 'cancelled' event and return its dict via
    # the normal task return path. We CANNOT use proxy.wait() because
    # wait() raises RuntimeError on a cancelled terminal state. Instead
    # we read the status row + read the producer's log via the
    # __mesh_job_status helper from the test driver.
    await asyncio.sleep(3.0)
    status = await proxy.status()
    return {
        "job_id": proxy.job_id,
        "work_seq": work_receipt["seq"],
        "terminal_status": status.get("status"),
        "terminal_error": status.get("error"),
    }


@app.tool()
@mesh.tool(
    capability="commission_subscribe_observer",
    dependencies=["run_until_done"],
    description="Submit run_until_done, concurrently post 'work' events and subscribe — verifies observer pattern.",
)
async def commission_subscribe_observer(
    run_until_done: MeshJob = None,
) -> dict:
    """Tc27 driver: producer consumes 'work' events; observer subscribes
    independently. Both sides must observe all 3 posted events; the
    producer's recv_event cursor is independent of the observer's.

    Sequence:
      1. Submit run_until_done.
      2. Concurrently:
         a) Background task fires 3 'work' events (the 3rd carries
            ``{"final": true}`` to terminate the producer).
         b) Background task subscribes via mesh.jobs.subscribe_events
            and collects every 'work' event until it sees the final one.
      3. Wait for both tasks + the producer to complete.
      4. Return a structured report so the integration assertions can
         pin all three observers (producer, subscriber, posters) agree
         on the event count and ordering.
    """
    if run_until_done is None:
        return {"error": "run_until_done submitter not injected"}
    proxy = await run_until_done.submit(ctx={}, max_duration=60)
    job_id = proxy.job_id

    # Give the producer a moment to claim + park on recv_event before we
    # post anything. Without this the first 'work' event could land
    # before the producer's claim worker has pulled the row off the
    # queue — the event would still be observable (the cursor is
    # per-controller), but the test would not exercise the long-poll
    # wake path.
    await asyncio.sleep(2.0)

    observed_events: list[dict] = []

    async def _subscriber() -> None:
        """Observe events via subscribe_events until the final one arrives."""
        async for event in mesh.jobs.subscribe_events(
            job_id, types=["work"], long_poll_secs=5.0
        ):
            observed_events.append(
                {"seq": event["seq"], "payload": event["payload"]}
            )
            payload = event.get("payload") or {}
            if isinstance(payload, dict) and payload.get("final"):
                return

    async def _poster() -> list[int]:
        """Fire 3 work events spaced ~500ms apart — last one terminates."""
        seqs: list[int] = []
        for i, payload in enumerate(
            [
                {"item": 1},
                {"item": 2},
                {"item": 3, "final": True},
            ]
        ):
            await asyncio.sleep(0.5)
            receipt = await mesh.jobs.post_event(
                job_id=job_id,
                event_type="work",
                payload=payload,
            )
            seqs.append(receipt["seq"])
        return seqs

    # Run subscriber + poster concurrently. The subscriber races the
    # producer for events but each has its own cursor, so both observe
    # the same set.
    sub_task = asyncio.create_task(_subscriber())
    posted_seqs = await _poster()

    # Bound the subscriber wait so a stuck observer doesn't hang the
    # whole test — 15s is well above the producer's expected runtime
    # (3 events * 500ms post-spacing + handler overhead).
    try:
        await asyncio.wait_for(sub_task, timeout=15.0)
        subscriber_status = "ok"
    except asyncio.TimeoutError:
        sub_task.cancel()
        # Drain the cancelled task so asyncio doesn't emit "Task was
        # destroyed but it is pending" warnings. The `Exception` arm
        # handles surfaces from the subscriber's error path — we've
        # already decided the subscriber didn't keep up, so the failure
        # mode of the drain is uninteresting.
        try:
            await sub_task
        except (asyncio.CancelledError, Exception):
            pass
        subscriber_status = "timeout"

    job_result = await proxy.wait(timeout_secs=30)

    return {
        "job_id": job_id,
        "posted_seqs": posted_seqs,
        "subscriber_status": subscriber_status,
        "observed_count": len(observed_events),
        "observed_events": observed_events,
        "job_result": job_result,
    }


# ---------------------------------------------------------------------------
# input_required lease-reclaim submitter (tc29 / C1, #1229)
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_awaits_input",
    dependencies=["awaits_input_forever"],
    description="Submit awaits_input_forever with a small max_duration and max_retries=0; never posts the answer.",
)
async def commission_awaits_input(
    user_id: str = "alice",
    max_duration: int = 2,
    awaits_input_forever: MeshJob = None,
) -> dict:
    if awaits_input_forever is None:
        return {"error": "awaits_input_forever submitter not injected"}
    # Small max_duration sizes the LEASE window so it lapses quickly once the
    # producer parks in input_required without heartbeating. max_retries=0
    # makes the lease lapse terminal on the first reclaim pass (status=failed,
    # error="lease expired: ..."), avoiding a reset→reclaim race that a
    # non-zero retry budget would introduce. We deliberately NEVER post the
    # "answer" event the producer is parked on.
    proxy = await awaits_input_forever.submit(
        user_id=user_id,
        max_duration=max_duration,
        max_retries=0,
    )
    return {"job_id": getattr(proxy, "job_id", None)}


# ---------------------------------------------------------------------------
# Durable recv_event cursor resume submitters (tc31 / tc32, issue #1277)
# ---------------------------------------------------------------------------
#
# Both submit-only: return the job_id and let the TC driver post the ``work``
# events + force the reclaim via meshctl and raw registry HTTP. max_retries=1
# budgets exactly the one forced reclaim (attempt 2). max_duration=60 sizes a
# lease window that poll-liveness (each recv_event round) keeps renewed, so the
# ONLY eviction actor is the admin reclaim — no natural lease lapse confounds.


@app.tool()
@mesh.tool(
    capability="commission_resume",
    dependencies=["resume_task"],
    description="Submit resume_task (resume_cursor ON) and return the job_id; driver posts events + reclaims.",
)
async def commission_resume(
    resume_task: MeshJob = None,
) -> dict:
    if resume_task is None:
        return {"error": "resume_task submitter not injected"}
    proxy = await resume_task.submit(ctx={}, max_duration=60, max_retries=1)
    return {"job_id": getattr(proxy, "job_id", None)}


@app.tool()
@mesh.tool(
    capability="commission_replay",
    dependencies=["replay_task"],
    description="Submit replay_task (resume_cursor OFF — control) and return the job_id; driver posts events + reclaims.",
)
async def commission_replay(
    replay_task: MeshJob = None,
) -> dict:
    if replay_task is None:
        return {"error": "replay_task submitter not injected"}
    proxy = await replay_task.submit(ctx={}, max_duration=60, max_retries=1)
    return {"job_id": getattr(proxy, "job_id", None)}


import os  # noqa: E402  (kept here for clarity that env-port is the only env hook)


@mesh.agent(
    name="long-task-consumer",
    version="1.0.0",
    description="MeshJob test consumer (uc21) — multi-capability fixture for the integration suite.",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9101")),
    enable_http=True,
    auto_run=True,
)
class LongTaskConsumer:
    pass
