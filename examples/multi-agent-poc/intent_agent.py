#!/usr/bin/env python3
"""
Intent Agent - Conversational orchestrator for multi-agent system

This agent serves as the user-facing interface that:
- Engages in natural conversation with users
- Identifies user intent through clarifying questions
- Delegates to specialist agents when tasks are clear
- Supports multi-turn conversations

Tags: ["intent", "orchestrator"]
"""

from typing import Any, Dict, List, Optional

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# Initialize MCP server
app = FastMCP("Intent Agent")


class IntentResponse(BaseModel):
    """
    Response from Intent Agent.

    The intent agent's response includes a conversational message to the user
    and optionally includes details about any specialist delegation.
    """

    message: str = Field(
        ...,
        description="Your conversational response message to the user. This field is REQUIRED.",
    )
    action_taken: Optional[str] = Field(
        None,
        description="Brief description of the action you took (e.g., 'Delegated to Developer', 'Asked clarifying question')",
    )
    specialist_used: Optional[str] = Field(
        None,
        description="Name of the specialist tool you called (e.g., 'develop') if you delegated the task",
    )
    specialist_response: Optional[Dict[str, Any]] = Field(
        None,
        description="The full response object returned by the specialist if you delegated",
    )


@app.tool()
@mesh.llm(
    filter={"tags": ["specialist"]},  # Filter for specialist agents
    filter_mode="all",
    provider={
        "capability": "llm",
        "tags": ["llm", "+claude"],
    },  # Mesh delegation with Claude preference
    model="anthropic/claude-sonnet-4-5",
    max_iterations=20,
    system_prompt="file://prompts/intent.jinja2",
)
@mesh.tool(
    capability="intent_orchestration",
    tags=["intent", "orchestrator", "chat"],
    version="1.0.0",
)
def chat(
    messages: List[Dict[str, Any]], llm: mesh.MeshLlmAgent = None
) -> IntentResponse:
    """
    Handle multi-turn conversation with user and orchestrate specialist agents.

    Args:
        messages: Conversation history in format:
            [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."},
                {"role": "user", "content": "..."}
            ]

    Returns:
        IntentResponse with conversational response and optional specialist results
    """
    # Use MeshLlmAgent's multi-turn conversation support
    return llm(messages)


@mesh.agent(
    name="intent-agent",
    version="1.0.0",
    description="Intent Agent - Conversational orchestrator for multi-agent system",
    http_port=9200,
    enable_http=True,
    auto_run=True,
)
class IntentAgent:
    """Intent agent that orchestrates user conversations and specialist delegation."""

    pass
