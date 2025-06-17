#!/usr/bin/env python3
"""
MCP Mesh LLM Chat Agent Example

This agent demonstrates basic LLM interaction using MCP-style messaging patterns.
Provides simple chat capabilities with system prompts and conversation management.

Usage:
- Basic chat with configurable models
- System prompt management
- Conversation history tracking
- Multi-turn dialogue support
"""

from datetime import datetime
from typing import Any

import mesh


@mesh.agent(name="llm-chat-agent", http_port=9093)
class LLMChatAgent:
    """LLM Chat agent providing conversational AI capabilities."""

    def __init__(self):
        self.conversations: dict[str, list[dict[str, str]]] = {}


# ===== BASIC CHAT SERVICE =====


@mesh.tool(
    capability="llm_chat",
    description="Basic chat with LLM using system prompts and user messages",
    version="1.0.0",
    tags=["llm", "chat", "ai", "conversation"],
)
def chat_with_llm(
    message: str,
    system_prompt: str | None = None,
    model: str = "claude-3-sonnet-20240229",
    conversation_id: str | None = None,
    max_tokens: int = 1000,
    temperature: float = 0.7,
) -> dict[str, Any]:
    """
    Chat with an LLM using MCP-style messaging.

    This follows the MCP conversation pattern with system prompts and user messages.

    Args:
        message: The user's message to send to the LLM
        system_prompt: Optional system prompt to set context
        model: LLM model to use (claude-3-sonnet, gpt-4, etc.)
        conversation_id: Optional ID to maintain conversation history
        max_tokens: Maximum tokens in response
        temperature: Creativity level (0.0-1.0)

    Returns:
        Dictionary with LLM response and metadata
    """

    # Build MCP-style message structure
    messages = []

    # Add system message if provided
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Add conversation history if maintaining a conversation
    if conversation_id and conversation_id in LLMChatAgent().conversations:
        messages.extend(LLMChatAgent().conversations[conversation_id])

    # Add current user message
    messages.append({"role": "user", "content": message})

    # Simulate LLM API call (in real implementation, this would call Anthropic/OpenAI API)
    try:
        # This would be the actual MCP client call:
        # response = await llm_client.call_method("messages/create", {
        #     "model": model,
        #     "messages": messages,
        #     "max_tokens": max_tokens,
        #     "temperature": temperature
        # })

        # Simulated response for example
        llm_response = f"[Simulated {model} response to: '{message[:50]}...']"

        # Store conversation history
        if conversation_id:
            if conversation_id not in LLMChatAgent().conversations:
                LLMChatAgent().conversations[conversation_id] = []

            # Add user message and assistant response to history
            LLMChatAgent().conversations[conversation_id].extend(
                [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": llm_response},
                ]
            )

        return {
            "response": llm_response,
            "model": model,
            "conversation_id": conversation_id,
            "message_count": len(messages),
            "timestamp": datetime.now().isoformat(),
            "usage": {
                "prompt_tokens": len(" ".join(msg["content"] for msg in messages))
                // 4,  # Rough estimate
                "completion_tokens": len(llm_response) // 4,
                "total_tokens": (
                    len(" ".join(msg["content"] for msg in messages))
                    + len(llm_response)
                )
                // 4,
            },
        }

    except Exception as e:
        return {
            "error": f"LLM chat failed: {str(e)}",
            "model": model,
            "conversation_id": conversation_id,
            "timestamp": datetime.now().isoformat(),
        }


# ===== SYSTEM PROMPT MANAGEMENT =====


@mesh.tool(
    capability="llm_system_prompt",
    description="Manage system prompts for different use cases",
    version="1.0.0",
    tags=["llm", "system", "prompt", "template"],
)
def create_system_prompt(
    role: str,
    personality: str = "helpful and knowledgeable",
    expertise: list[str] = None,
    constraints: list[str] = None,
    format: str = "conversational",
) -> dict[str, Any]:
    """
    Create a structured system prompt for LLM interactions.

    Args:
        role: The role the LLM should take (e.g., "assistant", "analyst", "tutor")
        personality: Personality traits for the LLM
        expertise: List of areas of expertise
        constraints: List of constraints or guidelines
        format: Response format preference

    Returns:
        Structured system prompt and metadata
    """

    expertise = expertise or []
    constraints = constraints or []

    # Build structured system prompt
    prompt_parts = [f"You are a {role} with a {personality} personality."]

    if expertise:
        prompt_parts.append(f"Your areas of expertise include: {', '.join(expertise)}.")

    if constraints:
        prompt_parts.append("Please follow these guidelines:")
        for constraint in constraints:
            prompt_parts.append(f"- {constraint}")

    prompt_parts.append(f"Respond in a {format} style.")

    system_prompt = " ".join(prompt_parts)

    return {
        "system_prompt": system_prompt,
        "role": role,
        "personality": personality,
        "expertise": expertise,
        "constraints": constraints,
        "format": format,
        "created_at": datetime.now().isoformat(),
        "prompt_length": len(system_prompt),
    }


# ===== CONVERSATION MANAGEMENT =====


@mesh.tool(
    capability="conversation_management",
    description="Manage conversation state and history",
    version="1.0.0",
    tags=["conversation", "history", "state"],
)
def manage_conversation(
    action: str, conversation_id: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Manage conversation state and history.

    Args:
        action: Action to perform ("create", "get", "clear", "list")
        conversation_id: ID of the conversation
        data: Additional data for certain actions

    Returns:
        Result of the conversation management action
    """

    agent = LLMChatAgent()

    if action == "create":
        agent.conversations[conversation_id] = []
        return {
            "action": "create",
            "conversation_id": conversation_id,
            "status": "created",
            "message_count": 0,
        }

    elif action == "get":
        messages = agent.conversations.get(conversation_id, [])
        return {
            "action": "get",
            "conversation_id": conversation_id,
            "messages": messages,
            "message_count": len(messages),
        }

    elif action == "clear":
        if conversation_id in agent.conversations:
            del agent.conversations[conversation_id]
            status = "cleared"
        else:
            status = "not_found"

        return {"action": "clear", "conversation_id": conversation_id, "status": status}

    elif action == "list":
        return {
            "action": "list",
            "conversations": {
                conv_id: len(messages)
                for conv_id, messages in agent.conversations.items()
            },
            "total_conversations": len(agent.conversations),
        }

    else:
        return {
            "error": f"Unknown action: {action}",
            "valid_actions": ["create", "get", "clear", "list"],
        }


# ===== MULTI-TURN DIALOGUE =====


@mesh.tool(
    capability="multi_turn_dialogue",
    description="Conduct multi-turn dialogue with context awareness",
    version="1.0.0",
    tags=["dialogue", "multi-turn", "context"],
)
def multi_turn_chat(
    messages: list[dict[str, str]],
    system_prompt: str | None = None,
    model: str = "claude-3-sonnet-20240229",
    maintain_context: bool = True,
) -> dict[str, Any]:
    """
    Conduct a multi-turn dialogue with the LLM.

    Args:
        messages: List of messages in the conversation
        system_prompt: Optional system prompt
        model: LLM model to use
        maintain_context: Whether to maintain conversation context

    Returns:
        LLM response with conversation metadata
    """

    # Validate message format
    for msg in messages:
        if "role" not in msg or "content" not in msg:
            return {
                "error": "Invalid message format. Each message must have 'role' and 'content' fields."
            }

        if msg["role"] not in ["user", "assistant", "system"]:
            return {
                "error": f"Invalid role: {msg['role']}. Must be 'user', 'assistant', or 'system'."
            }

    # Build full conversation context
    full_messages = []

    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})

    full_messages.extend(messages)

    # Simulate LLM response (in real implementation, call actual LLM API)
    try:
        # This would be the actual API call
        llm_response = f"[Simulated {model} response to multi-turn conversation with {len(messages)} messages]"

        return {
            "response": llm_response,
            "model": model,
            "conversation_length": len(full_messages),
            "context_maintained": maintain_context,
            "timestamp": datetime.now().isoformat(),
            "message_roles": [msg["role"] for msg in messages],
            "total_characters": sum(len(msg["content"]) for msg in messages),
        }

    except Exception as e:
        return {
            "error": f"Multi-turn chat failed: {str(e)}",
            "model": model,
            "conversation_length": len(full_messages),
        }


# 🎉 Pure MCP Mesh simplicity with LLM chat capabilities!
# No manual setup needed - just decorators for conversational AI!
