#!/usr/bin/env python3
"""
ticket-agent-typed - Python @mesh.llm consumer that CATCHES the typed
buffered-exhaustion error (issue #1355).

WHAT #1355 CHANGED
------------------
Before #1355 the Python provider-managed agentic loop signalled exhaustion by
returning a synthetic assistant string ("Maximum tool call iterations reached").
#1355 removed that sentinel: the loop now surfaces a STRUCTURAL discriminant
(``_mesh_stop_reason == "max_iterations"``) and the consumer's MeshLlmAgent
RAISES a typed ``mesh.MaxIterationsError`` (see
_mcp_mesh/engine/mesh_llm_agent.py). The failure is NEVER carried in ``content``.

WHAT THIS AGENT PROVES
----------------------
That a capped buffered call raises ``mesh.MaxIterationsError`` (the public
export) rather than returning a completed answer or the old sentinel text. The
handler catches the type and re-emits a machine-checkable sentinel that names
the exception CLASS and its ``max_allowed`` attribute:

    EXHAUSTED_TYPED type=MaxIterationsError max=1

The tc asserts on that class name — deliberately NOT on the removed
"Maximum tool call iterations reached" string.

DETERMINISM (shared with tc45/tc46/tc47)
----------------------------------------
Configured with an explicit ``max_iterations=1`` and filtered to the single
``iteration_probe`` capability (advance_ticket) on iteration-probe-agent. The
probe ticket needs FOUR advance_ticket rounds to reach COMPLETE, so a cap of 1
forces the loop to exhaust after exactly one tool round. The tc reads the
probe's out-of-band invocation counter to prove one round ran (PROBE_INVOCATIONS
=[1]); a [0] count would mean the model answered without the tool and nothing
was measured.
"""

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("TicketAgentTyped")


class TicketContext(BaseModel):
    """Context for the ticket-processing request."""

    instruction: str = Field(
        ..., description="Instruction describing the multi-step ticket to process"
    )


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude", "+provider"]},
    # Only advance_ticket is exposed to the model. probe_count / probe_reset sit
    # on DIFFERENT capabilities so the model can neither read nor reset the
    # counter it is being measured with.
    filter={"capability": "iteration_probe"},
    # Explicit cap -> forwarded as model_params.max_iterations. Combined with the
    # 4-step ticket this forces the provider-managed loop to exhaust.
    max_iterations=1,
    system_prompt=(
        "You are a ticket-processing agent. You MUST use the advance_ticket "
        "tool to make progress on a ticket; never guess, fabricate or predict a "
        "token, a step number or a final_code. Call advance_ticket AT MOST ONCE "
        "per turn and wait for its result before calling it again — the token "
        "for the next call only exists in the previous call's response. Keep "
        "going until the tool reports status COMPLETE, then reply with the "
        "final_code it returned."
    ),
    context_param="ctx",
)
@mesh.tool(
    capability="run_ticket",
    description="Drive the probe ticket to completion using the advance_ticket tool",
    version="1.0.0",
    tags=["llm", "ticket", "iteration"],
)
async def run_ticket(
    ctx: TicketContext,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """Hand the ticket to the mesh LLM provider and catch typed exhaustion.

    A capped provider-managed loop RAISES ``mesh.MaxIterationsError`` (issue
    #1355) — the failure is structural and never appears in the returned text.
    We convert it to a sentinel that names the exception class so the test can
    assert on the TYPE rather than any (removed) sentinel string.
    """
    if llm is None:
        raise RuntimeError("Mesh provider not resolved for run_ticket")

    try:
        return await llm(ctx.instruction)
    except mesh.MaxIterationsError as e:
        return f"EXHAUSTED_TYPED type={type(e).__name__} max={e.max_allowed}"


@mesh.agent(
    name="ticket-agent-typed",
    version="1.0.0",
    description="Consumer that catches typed buffered exhaustion (issue #1355)",
    http_port=9048,
    enable_http=True,
    auto_run=True,
)
class TicketAgentTypedConfig:
    """Consumer agent for the buffered typed-exhaustion tc."""

    pass
