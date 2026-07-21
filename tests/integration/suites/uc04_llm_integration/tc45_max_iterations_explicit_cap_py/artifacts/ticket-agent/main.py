#!/usr/bin/env python3
"""
ticket-agent - Python @mesh.llm consumer with an EXPLICIT max_iterations=1 (tc45).

Issue #1356: before PR #1359 the consumer's ``max_iterations`` never went on the
wire and the Python provider's agentic loop hardcoded 10, so
``@mesh.llm(max_iterations=N)`` was INERT on the mesh-delegated path.

This agent is the minimal consumer that proves the fix end-to-end:
  - it declares max_iterations=1 EXPLICITLY (so the value is forwarded as
    model_params.max_iterations),
  - it filters in exactly ONE mesh tool (capability "iteration_probe" ->
    advance_ticket on iteration-probe-agent), and
  - the prompt it is driven with requires FOUR sequential advance_ticket rounds
    to finish the ticket.

With the cap honored the provider-managed loop executes advance_ticket exactly
ONCE. Without it, the loop runs to completion (4 invocations). The tc reads the
probe agent's invocation counter to tell those apart — deliberately NOT the
provider's "Maximum tool call iterations reached" sentinel, which issue #1355
will replace with a structured signal.

Return type is plain ``str``: when the loop is capped, the provider returns its
exhaustion payload rather than a completed answer, and a structured/Pydantic
return type would turn that into an unrelated validation error instead of the
observable under test.
"""

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("TicketAgent")


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
    # THE THING UNDER TEST: an explicitly configured cap must be forwarded to
    # the provider-managed loop (model_params.max_iterations).
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
    """Hand the ticket instruction to the mesh LLM provider."""
    if llm is None:
        raise RuntimeError("Mesh provider not resolved for run_ticket")

    return await llm(ctx.instruction)


@mesh.agent(
    name="ticket-agent",
    version="1.0.0",
    description="Consumer with explicit max_iterations=1 (issue #1356)",
    http_port=9037,
    enable_http=True,
    auto_run=True,
)
class TicketAgentConfig:
    """Consumer agent for tc45."""

    pass
