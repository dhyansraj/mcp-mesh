#!/usr/bin/env python3
"""
ticket-agent-unset - Python @mesh.llm consumer that configures NO cap (tc46).

Issue #1356 contract: ``max_iterations`` is forwarded to the provider ONLY when
the consumer explicitly configured it (decorator argument or consumer-side
MESH_LLM_MAX_ITERATIONS). When the consumer says nothing, the key must be ABSENT
from the wire so the PROVIDER's own MESH_LLM_MAX_ITERATIONS (or its default of
10) applies.

This agent is the "says nothing" half of that contract: it is byte-for-byte the
tc45 consumer MINUS the ``max_iterations`` argument. Everything else — provider
selector, tool filter, system prompt — is identical on purpose, so the only
variable between tc45 and tc46 is who configures the cap.

If the runtime were to forward a value unconditionally (e.g. always sending the
default 10), that forwarded 10 would SHADOW the provider's env and the tc46
assertion would fail. That is exactly what makes this tc a real test of
explicit-only forwarding rather than a restatement of tc45.
"""

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("TicketAgentUnset")


class TicketContext(BaseModel):
    """Context for the ticket-processing request."""

    instruction: str = Field(
        ..., description="Instruction describing the multi-step ticket to process"
    )


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude", "+provider"]},
    filter={"capability": "iteration_probe"},
    # NO max_iterations HERE. This is the point of tc46: nothing must go on the
    # wire, leaving the provider's MESH_LLM_MAX_ITERATIONS in charge.
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
    name="ticket-agent-unset",
    version="1.0.0",
    description="Consumer with NO configured max_iterations (issue #1356)",
    http_port=9038,
    enable_http=True,
    auto_run=True,
)
class TicketAgentUnsetConfig:
    """Consumer agent for tc46."""

    pass
