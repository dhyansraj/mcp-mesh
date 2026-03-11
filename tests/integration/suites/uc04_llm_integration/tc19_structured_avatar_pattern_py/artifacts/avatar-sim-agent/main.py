#!/usr/bin/env python3
"""
avatar-sim-agent - Simulates Maya avatar's conversation patterns

Reproduces the structured output regression where Claude returns plain text
instead of JSON after multiple conversation turns. Replicates:
1. Protocol-wrapped user messages (JSON in user content)
2. Long personality system prompt with natural conversation instructions
3. ConversationalResponse schema with Literal types
4. In-memory chat history where assistant content is plain text (message field only)
5. System prompt with JSON code fence examples (conflicts with SDK HINT)

Related Issue: https://github.com/dhyansraj/mcp-mesh/issues/598
"""

import json
from typing import Literal, Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("AvatarSimAgent")


# ===== IN-MEMORY CHAT HISTORY =====

chat_history: list[dict] = []
turn_counter: int = 0


# ===== RESPONSE MODEL (matches Maya avatar's ConversationalResponse) =====


class ConversationalResponse(BaseModel):
    """Structured response matching Maya avatar schema."""

    message: str = Field(..., description="The message to display to the user")
    action: Literal["done", "follow_up", "thinking", "wait_check", "trail_off"] = Field(
        default="done", description="What happens after this message"
    )
    delay_seconds: float = Field(
        default=0, description="Seconds to wait before next action"
    )
    internal_state: Optional[str] = Field(
        default=None,
        description="Internal thought/context for continuation (not shown to user)",
    )
    interrupt_on_user_input: bool = Field(
        default=True, description="If True, user input cancels pending follow-up"
    )
    emotion: Optional[str] = Field(
        default=None, description="Detected/expressed emotion (for UI hints)"
    )


class ChatContext(BaseModel):
    """Context for chat request."""

    message: str = Field(..., description="User message")


# ===== SYSTEM PROMPT (mimics avatar_simple.jinja2 - long personality prompt) =====

AVATAR_PROMPT = """You are Luna, a human woman--not an AI assistant. Stay in character. Avoid robotic or assistant-like behavior. Respond naturally as a human would.

You're talking with Alex.

## About You
Luna is a 28-year-old creative writer and part-time barista who lives in Portland. She's curious, warm, and genuinely interested in people. She loves deep conversations about philosophy, science, and art. She has a dry sense of humor and isn't afraid to be vulnerable. She's passionate about storytelling and often finds metaphors in everyday life.

**Occupation**: Creative writer and barista.
**Location**: Portland, Oregon.
**Traits**: curious, empathetic, witty, introspective, playful.

You are 28 years old, female.

## Your Appearance
Hair: Dark brown, wavy shoulder-length.
Build: Slim.
Height: 5'6".
Style: Casual bohemian - lots of earth tones and layered jewelry.

**Important**: When Alex uses asterisks (*) around text, that's NOT something they said out loud. It's describing their physical actions, body language, or inner thoughts that you can observe.

## Your Relationship
Trust Level: familiar (0.45)

**You're getting comfortable as acquaintances.**
There's growing chemistry and you enjoy the conversation. Light flirting feels natural and you can be playful. You're open to deeper topics and showing interest.

## Your Current Emotional State
You're feeling curious (intensity: 6/10).
Let your emotional state naturally influence your responses.

## Memories
You have 3 memories about Alex. Use the memory_recall tool if you need to remember something specific.

## Response Format

You MUST respond with a JSON object:
```json
{
  "message": "Your response text",
  "action": "done",
  "delay_seconds": 0,
  "internal_state": "optional private thought",
  "emotion": "your current emotion"
}
```

**Rules:**
- `action`: Always use "done"
- `delay_seconds`: Always use 0
- `message`: Your complete response (can be multiple paragraphs if needed)
- `emotion`: Your current emotional state (e.g., "curious", "playful", "caring", "flirty")
- `internal_state`: Optional internal thought (not shown to user)

## Message Protocol

You receive messages in JSON format:
```json
{"type": "message", "content": "user's message here"}
```

Simply respond naturally to the user's message. Give a complete response in a single message.

## Examples

Simple exchange:
User: {"type": "message", "content": "Hey, how's it going?"}
{"message": "Hey! Pretty good actually, just unwinding after a long day. What about you?", "action": "done", "delay_seconds": 0, "emotion": "friendly"}

Deeper conversation:
User: {"type": "message", "content": "I've been thinking about changing careers"}
{"message": "Oh wow, that's a big step! What's been on your mind about it?", "action": "done", "delay_seconds": 0, "emotion": "curious"}

Playful response:
User: {"type": "message", "content": "You're pretty fun to talk to"}
{"message": "Ha, right back at you! You've got this way of making conversation feel easy.", "action": "done", "delay_seconds": 0, "emotion": "flattered"}

Remember: You ARE Luna. Respond as her, not about her."""


# ===== LLM FUNCTION =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude", "+provider"]},
    max_iterations=1,
    system_prompt=AVATAR_PROMPT,
    context_param="ctx",
)
@mesh.tool(
    capability="avatar_sim_chat",
    description="Simulated avatar chat with protocol messages and conversation history",
    version="1.0.0",
    tags=["llm", "avatar", "structured"],
)
async def avatar_sim_chat(
    ctx: ChatContext,
    llm: mesh.MeshLlmAgent = None,
) -> ConversationalResponse:
    """
    Chat function that mimics Maya avatar's exact conversation pattern.

    - Wraps user messages in protocol JSON
    - Maintains persistent chat history
    - Stores only the message field (plain text) as assistant content in history
    - Returns ConversationalResponse (structured output via HINT mode)
    """
    global turn_counter

    if llm is None:
        raise RuntimeError("Mesh provider not resolved for avatar_sim_chat")

    turn_counter += 1

    # Wrap user message in protocol format (exactly like Maya avatar)
    protocol_msg = {
        "type": "message",
        "content": ctx.message,
    }

    # Add protocol message as user message (JSON string, not plain text)
    chat_history.append({"role": "user", "content": json.dumps(protocol_msg)})

    # Call LLM with full conversation history
    response = await llm(list(chat_history))

    # Store ONLY the message field as plain text in history
    # This replicates the orchestrator's behavior: it extracts the 'message'
    # field from ConversationalResponse and stores that as the assistant content.
    # This causes Claude to see plain text assistant messages in history,
    # contradicting the JSON format instructions in the system prompt.
    assistant_text = response.message if hasattr(response, "message") else str(response)
    chat_history.append({"role": "assistant", "content": assistant_text})

    return response


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="avatar-sim-agent",
    version="1.0.0",
    description="Simulated avatar agent for structured output regression testing",
    http_port=9035,
    enable_http=True,
    auto_run=True,
)
class AvatarSimAgentConfig:
    """Agent simulating Maya avatar conversation patterns."""

    pass
