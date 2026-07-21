#!/usr/bin/env python3
"""
iteration-probe-agent - deterministic agentic-loop iteration counter (issue #1356).

WHY THIS AGENT EXISTS
---------------------
Issue #1356 / PR #1359 made a consumer's ``max_iterations`` reach the
PROVIDER-managed agentic loop on the wire (``model_params.max_iterations``).
Proving that end-to-end needs an observable that says *how many tool rounds the
provider-managed loop actually executed*.

The obvious observable is the provider's exhaustion sentinel
("Maximum tool call iterations reached"), but issue #1355 is going to replace
that synthetic message with a structured signal. Any test that asserts on it
breaks the moment #1355 lands. So this agent provides a signal that is
independent of BOTH the sentinel text and the provider's log format: an
in-process invocation COUNTER.

TOOL LAYOUT (3 tools, deliberately on 3 DIFFERENT capabilities)
---------------------------------------------------------------
  advance_ticket  capability="iteration_probe"  <- the ONLY tool consumers filter
                  in, i.e. the only tool the LLM ever sees. Increments the
                  counter on every invocation.
  probe_count     capability="probe_count"      <- readout, called DIRECTLY by the
                  test via `meshctl call`. NOT matched by the consumers'
                  filter={"capability": "iteration_probe"}, so the LLM can never
                  call it and can never perturb the measurement.
  probe_reset     capability="probe_reset"      <- zeroes the counter, called
                  DIRECTLY by the test right before the measured call so any
                  warm-up / readiness traffic cannot contaminate the count.
                  Also invisible to the LLM for the same reason.

FORCED SEQUENTIALITY (why the count is a faithful iteration count)
------------------------------------------------------------------
``advance_ticket`` takes a ``token`` and returns a RANDOM ``next_token`` that the
model cannot guess. The model therefore cannot batch several ``advance_ticket``
calls into a single turn — it must wait for each result before it can produce
the next token. One tool round == one counter increment, so
``probe_count`` reports exactly how many agentic-loop tool rounds ran.

The ticket only reaches ``status="COMPLETE"`` after TOTAL_STEPS (4) invocations,
so an UNCAPPED run (provider default of 10) reliably produces 4 invocations.
A run capped at 1 produces exactly 1. That gap is what the tcs assert on.
"""

import uuid
from typing import Any

from fastmcp import FastMCP

import mesh

app = FastMCP("IterationProbeAgent")

# Number of advance_ticket invocations before the ticket reports COMPLETE.
# Chosen > 1 so a capped (1) run and an uncapped (default 10) run are clearly
# distinguishable, and small enough that an uncapped run stays cheap/bounded.
TOTAL_STEPS = 4

# Sentinel the model can only ever learn by driving the ticket all the way to
# completion. Its ABSENCE from a capped run's answer is a secondary, sentinel-
# text-independent proof that the loop stopped early.
FINAL_CODE = "PROBE-COMPLETE-9F3A"

_state: dict[str, Any] = {"invocations": 0}


@app.tool()
@mesh.tool(
    capability="iteration_probe",
    description=(
        "Advance the ticket by EXACTLY ONE step. Pass the token you were given "
        "('START' for the first call, otherwise the 'next_token' from the "
        "previous response). Returns status INCOMPLETE plus a new next_token "
        "until the ticket is finished, then status COMPLETE with the final_code. "
        "You cannot know the next token without calling this tool first, so call "
        "it once, read the result, then call it again."
    ),
    version="1.0.0",
    tags=["probe", "loop", "iteration"],
)
def advance_ticket(token: str) -> dict:
    """Advance the probe ticket one step and count the invocation.

    The counter is incremented UNCONDITIONALLY (the token is never validated) so
    that ``probe_count`` reports the literal number of times the agentic loop
    executed this tool — nothing else. Validating the token would make the count
    depend on the model echoing it correctly, which is exactly the kind of
    LLM-dependent flakiness this probe is meant to avoid.
    """
    _state["invocations"] += 1
    step = _state["invocations"]

    if step >= TOTAL_STEPS:
        return {
            "status": "COMPLETE",
            "step": step,
            "final_code": FINAL_CODE,
            "instruction": (
                "The ticket is COMPLETE. Reply with the final_code and stop "
                "calling tools."
            ),
        }

    return {
        "status": "INCOMPLETE",
        "step": step,
        "steps_remaining": TOTAL_STEPS - step,
        # Unguessable: forces the model to serialize its tool calls (one per
        # turn) instead of batching several into a single iteration.
        "next_token": f"T-{uuid.uuid4().hex[:12]}",
        "instruction": (
            "The ticket is NOT finished. Call advance_ticket again, passing the "
            "next_token above as 'token'. Repeat until status is COMPLETE."
        ),
    }


@app.tool()
@mesh.tool(
    capability="probe_count",
    description="Report how many times advance_ticket has been invoked.",
    version="1.0.0",
    tags=["probe", "readout"],
)
def probe_count() -> str:
    """Readout for the test harness (never exposed to the LLM).

    Returns a bracketed marker so a plain substring assertion is unambiguous:
    'PROBE_INVOCATIONS=[1]' can never accidentally match a count of 10 or 11.
    """
    return f"PROBE_INVOCATIONS=[{_state['invocations']}]"


@app.tool()
@mesh.tool(
    capability="probe_reset",
    description="Reset the advance_ticket invocation counter to zero.",
    version="1.0.0",
    tags=["probe", "reset"],
)
def probe_reset() -> str:
    """Zero the counter (never exposed to the LLM).

    Called by the test immediately before the MEASURED call so readiness /
    warm-up traffic cannot contaminate the measurement.
    """
    _state["invocations"] = 0
    return "PROBE_RESET_OK"


@mesh.agent(
    name="iteration-probe-agent",
    version="1.0.0",
    description="Deterministic agentic-loop iteration counter for issue #1356",
    http_port=9036,
    enable_http=True,
    auto_run=True,
)
class IterationProbeAgentConfig:
    """Probe tool provider for the max_iterations forwarding tcs."""

    pass
