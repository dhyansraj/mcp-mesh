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
from fastmcp import FastMCP

# Create FastMCP app instance
app = FastMCP("LLM Service")


@mesh.agent(name="llm-chat-agent", http_port=9093, auto_run=True)
class LLMChatAgent:
    """LLM Chat agent providing conversational AI capabilities."""

    def __init__(self):
        self.conversations: dict[str, list[dict[str, str]]] = {}


# ===== BASIC CHAT SERVICE =====


@app.tool()
@mesh.tool(
    capability="llm-service",
    description="LLM service for text processing and analysis",
    version="1.0.0",
    tags=["llm", "service", "ai", "processing", "analysis"],
)
def process_text_with_llm(
    text: str,
    task: str = "analyze",
    context: str | None = None,
    model: str = "claude-3-sonnet-20240229",
    max_tokens: int = 1000,
    temperature: float = 0.7,
) -> dict[str, Any]:
    """
    Process text with LLM for various tasks like analysis, summarization, etc.

    Args:
        text: The text to process
        task: Processing task (analyze, summarize, interpret, classify, extract)
        context: Optional context for the processing task
        model: LLM model to use
        max_tokens: Maximum tokens in response
        temperature: Creativity level (0.0-1.0)

    Returns:
        Dictionary with LLM processing results and metadata
    """

    # Build task-specific system prompt
    task_prompts = {
        "analyze": "Analyze the provided text and provide insights about its content, structure, and meaning.",
        "summarize": "Provide a concise summary of the key points in the text.",
        "interpret": "Interpret the meaning and implications of the text.",
        "classify": "Classify the text into appropriate categories.",
        "extract": "Extract key information and entities from the text.",
        "sentiment": "Analyze the sentiment and emotional tone of the text.",
        "keywords": "Extract important keywords and phrases from the text."
    }
    
    system_prompt = task_prompts.get(task, "Process the provided text as requested.")
    if context:
        system_prompt += f" Context: {context}"
    
    # Build message structure
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Please {task} this text:\n\n{text}"}
    ]

    # Simulate LLM API call (in real implementation, this would call Anthropic/OpenAI API)
    try:
        # This would be the actual MCP client call:
        # response = await llm_client.call_method("messages/create", {
        #     "model": model,
        #     "messages": messages,
        #     "max_tokens": max_tokens,
        #     "temperature": temperature
        # })

        # Simulated task-specific response
        task_responses = {
            "analyze": f"Analysis of text (length: {len(text)} chars): This text appears to contain structured data with various elements that could be processed for insights.",
            "summarize": f"Summary: The text contains {len(text.split())} words and covers topics that would benefit from summarization.",
            "interpret": f"Interpretation: This text can be interpreted as containing meaningful information suitable for further processing.",
            "classify": f"Classification: Based on content analysis, this text falls into data processing categories.",
            "extract": f"Extracted entities: Found {len(text.split())} words that could contain extractable information.",
            "sentiment": "Sentiment: The text appears to have a neutral to positive sentiment based on language patterns.",
            "keywords": f"Keywords: {', '.join(text.split()[:5])}..."
        }
        
        llm_response = task_responses.get(task, f"[Simulated {model} {task} response for text: '{text[:50]}...']")

        # No conversation history for service calls - each call is independent

        return {
            "result": llm_response,
            "task": task,
            "model": model,
            "input_length": len(text),
            "context": context,
            "timestamp": datetime.now().isoformat(),
            "usage": {
                "prompt_tokens": len(" ".join(msg["content"] for msg in messages)) // 4,
                "completion_tokens": len(llm_response) // 4,
                "total_tokens": (len(" ".join(msg["content"] for msg in messages)) + len(llm_response)) // 4,
            },
        }

    except Exception as e:
        return {
            "error": f"LLM processing failed: {str(e)}",
            "task": task,
            "model": model,
            "timestamp": datetime.now().isoformat(),
        }


# ===== DATA PROCESSING ASSISTANCE =====

@app.tool()
@mesh.tool(
    capability="data_interpretation",
    description="Interpret and provide insights about data processing results",
    version="1.0.0",
    tags=["llm", "data", "interpretation", "insights"],
)
def interpret_data_results(
    data_summary: dict[str, Any],
    analysis_type: str = "general",
    focus_areas: list[str] = None,
) -> dict[str, Any]:
    """
    Interpret data processing results and provide insights.
    
    Args:
        data_summary: Summary of processed data
        analysis_type: Type of analysis needed (general, statistical, quality, trends)
        focus_areas: Specific areas to focus on
        
    Returns:
        Dictionary with interpretation and insights
    """
    focus_areas = focus_areas or []
    
    try:
        # Simulate LLM interpretation of data results
        interpretation_prompts = {
            "general": "Provide general insights about this data processing result",
            "statistical": "Focus on statistical patterns and anomalies in the data",
            "quality": "Assess data quality and identify potential issues",
            "trends": "Identify trends and patterns in the processed data"
        }
        
        # Build context for interpretation
        context = f"Data processing results: {data_summary}"
        if focus_areas:
            context += f" Focus on: {', '.join(focus_areas)}"
        
        # Simulated LLM interpretation
        insights = f"Based on the {analysis_type} analysis, the data shows characteristics typical of {data_summary.get('format', 'unknown')} format. "
        if 'validation_report' in data_summary:
            insights += "Data validation appears successful. "
        if 'metadata' in data_summary:
            insights += f"Metadata indicates {data_summary['metadata']} structure. "
        
        return {
            "interpretation": insights,
            "analysis_type": analysis_type,
            "focus_areas": focus_areas,
            "confidence": 0.85,
            "recommendations": [
                "Consider additional validation steps",
                "Monitor data quality metrics",
                "Review processing pipeline efficiency"
            ],
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "error": f"Data interpretation failed: {str(e)}",
            "analysis_type": analysis_type,
            "timestamp": datetime.now().isoformat()
        }


# ===== SYSTEM PROMPT MANAGEMENT =====


@app.tool()
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


@app.tool()
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


@app.tool()
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
