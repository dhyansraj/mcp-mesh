#!/usr/bin/env python3
"""
MCP Mesh LLM Sampling Agent Example

This agent demonstrates the official MCP Sampling Protocol for LLM interactions.
Implements the `sampling/createMessage` method and related MCP sampling features.

Based on MCP Specification:
https://spec.modelcontextprotocol.io/specification/basic/sampling/

Usage:
- Official MCP sampling protocol
- Model preferences and hints
- Progress tracking for sampling
- Cancellation support
- Resource integration for sampling
"""

from datetime import datetime
from enum import Enum
from typing import Any

import mesh


@mesh.agent(name="llm-sampling-agent", http_port=9094)
class LLMSamplingAgent:
    """LLM Sampling agent implementing official MCP Sampling Protocol."""

    def __init__(self):
        self.active_samplings: dict[str, dict[str, Any]] = {}
        self.sampling_history: list[dict[str, Any]] = []


# ===== MCP SAMPLING PROTOCOL IMPLEMENTATION =====


class SamplingRole(str, Enum):
    """MCP-compliant message roles."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ModelHintType(str, Enum):
    """MCP model hint types."""

    MODEL = "model"
    PROVIDER = "provider"
    CAPABILITY = "capability"


@mesh.tool(
    capability="mcp_sampling",
    description="Official MCP sampling/createMessage implementation",
    version="1.0.0",
    tags=["mcp", "sampling", "llm", "official"],
)
def sampling_create_message(
    messages: list[dict[str, Any]],
    model_preferences: dict[str, Any] | None = None,
    system_prompt: str | None = None,
    include_context: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    stop_sequences: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Official MCP sampling/createMessage implementation.

    This follows the exact MCP specification for LLM sampling requests.

    Args:
        messages: Array of message objects with role and content
        model_preferences: MCP model preferences with hints
        system_prompt: Optional system prompt for the conversation
        include_context: Optional context inclusion mode
        temperature: Sampling temperature (0.0-1.0)
        max_tokens: Maximum tokens to generate
        stop_sequences: List of sequences that stop generation
        metadata: Additional metadata for the request

    Returns:
        MCP-compliant sampling response
    """

    # Validate MCP message format
    for i, message in enumerate(messages):
        if not isinstance(message, dict):
            return {
                "error": {
                    "code": -32602,
                    "message": f"Invalid message format at index {i}: must be object",
                }
            }

        if "role" not in message or "content" not in message:
            return {
                "error": {
                    "code": -32602,
                    "message": f"Invalid message at index {i}: missing 'role' or 'content'",
                }
            }

        if message["role"] not in [role.value for role in SamplingRole]:
            return {
                "error": {
                    "code": -32602,
                    "message": f"Invalid role '{message['role']}' at index {i}",
                }
            }

    # Process model preferences according to MCP spec
    selected_model = "claude-3-sonnet-20240229"  # Default
    model_provider = "anthropic"

    if model_preferences and "hints" in model_preferences:
        for hint in model_preferences["hints"]:
            if hint.get("type") == "model" and "name" in hint:
                selected_model = hint["name"]
            elif hint.get("type") == "provider" and "name" in hint:
                model_provider = hint["name"]

    # Generate unique sampling ID
    sampling_id = f"sampling-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{len(LLMSamplingAgent().active_samplings)}"

    # Build MCP-compliant request
    sampling_request = {
        "id": sampling_id,
        "messages": messages,
        "model": selected_model,
        "provider": model_provider,
        "parameters": {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stop_sequences": stop_sequences,
        },
        "system_prompt": system_prompt,
        "include_context": include_context,
        "metadata": metadata or {},
        "created_at": datetime.now().isoformat(),
    }

    # Store active sampling
    LLMSamplingAgent().active_samplings[sampling_id] = sampling_request

    try:
        # This would be the actual MCP client call to LLM provider:
        # response = await mcp_client.call_method("sampling/createMessage", sampling_request)

        # Simulated MCP-compliant response
        simulated_content = f"[Simulated {selected_model} response to {len(messages)} messages via MCP sampling]"

        mcp_response = {
            "model": selected_model,
            "stopReason": "endTurn",  # MCP-compliant stop reason
            "role": SamplingRole.ASSISTANT.value,
            "content": {"type": "text", "text": simulated_content},
            "usage": {
                "inputTokens": sum(len(msg.get("content", "")) for msg in messages)
                // 4,
                "outputTokens": len(simulated_content) // 4,
                "totalTokens": (
                    sum(len(msg.get("content", "")) for msg in messages)
                    + len(simulated_content)
                )
                // 4,
            },
            "metadata": {
                "sampling_id": sampling_id,
                "provider": model_provider,
                "request_timestamp": sampling_request["created_at"],
                "response_timestamp": datetime.now().isoformat(),
            },
        }

        # Store in history
        LLMSamplingAgent().sampling_history.append(
            {"request": sampling_request, "response": mcp_response}
        )

        # Remove from active samplings
        del LLMSamplingAgent().active_samplings[sampling_id]

        return mcp_response

    except Exception as e:
        # MCP-compliant error response
        error_response = {
            "error": {
                "code": -32603,
                "message": f"Sampling failed: {str(e)}",
                "data": {
                    "sampling_id": sampling_id,
                    "model": selected_model,
                    "provider": model_provider,
                },
            }
        }

        # Remove from active samplings on error
        if sampling_id in LLMSamplingAgent().active_samplings:
            del LLMSamplingAgent().active_samplings[sampling_id]

        return error_response


# ===== MCP SAMPLING PROGRESS =====


@mesh.tool(
    capability="sampling_progress",
    description="Track progress of active sampling operations",
    version="1.0.0",
    tags=["mcp", "sampling", "progress", "streaming"],
)
def get_sampling_progress(sampling_id: str | None = None) -> dict[str, Any]:
    """
    Get progress information for active sampling operations.

    Args:
        sampling_id: Optional specific sampling ID to check

    Returns:
        Progress information for sampling operations
    """

    agent = LLMSamplingAgent()

    if sampling_id:
        if sampling_id in agent.active_samplings:
            sampling = agent.active_samplings[sampling_id]
            return {
                "sampling_id": sampling_id,
                "status": "active",
                "model": sampling["model"],
                "provider": sampling["provider"],
                "started_at": sampling["created_at"],
                "duration_seconds": (
                    datetime.now() - datetime.fromisoformat(sampling["created_at"])
                ).total_seconds(),
                "message_count": len(sampling["messages"]),
            }
        else:
            return {
                "sampling_id": sampling_id,
                "status": "not_found",
                "error": "Sampling ID not found in active samplings",
            }
    else:
        # Return all active samplings
        active_progress = []
        for sid, sampling in agent.active_samplings.items():
            active_progress.append(
                {
                    "sampling_id": sid,
                    "status": "active",
                    "model": sampling["model"],
                    "provider": sampling["provider"],
                    "started_at": sampling["created_at"],
                    "duration_seconds": (
                        datetime.now() - datetime.fromisoformat(sampling["created_at"])
                    ).total_seconds(),
                }
            )

        return {
            "active_samplings": active_progress,
            "total_active": len(active_progress),
            "total_completed": len(agent.sampling_history),
        }


# ===== MCP SAMPLING CANCELLATION =====


@mesh.tool(
    capability="sampling_cancellation",
    description="Cancel active sampling operations",
    version="1.0.0",
    tags=["mcp", "sampling", "cancellation", "control"],
)
def cancel_sampling(sampling_id: str, reason: str = "user_requested") -> dict[str, Any]:
    """
    Cancel an active sampling operation.

    Args:
        sampling_id: ID of the sampling to cancel
        reason: Reason for cancellation

    Returns:
        Cancellation result
    """

    agent = LLMSamplingAgent()

    if sampling_id not in agent.active_samplings:
        return {
            "error": {
                "code": -32602,
                "message": f"Sampling ID '{sampling_id}' not found",
            }
        }

    # Get sampling info before removal
    sampling = agent.active_samplings[sampling_id]

    # Remove from active samplings
    del agent.active_samplings[sampling_id]

    # Add to history with cancellation info
    agent.sampling_history.append(
        {
            "request": sampling,
            "response": {
                "status": "cancelled",
                "reason": reason,
                "cancelled_at": datetime.now().isoformat(),
                "duration_seconds": (
                    datetime.now() - datetime.fromisoformat(sampling["created_at"])
                ).total_seconds(),
            },
        }
    )

    return {
        "sampling_id": sampling_id,
        "status": "cancelled",
        "reason": reason,
        "cancelled_at": datetime.now().isoformat(),
        "model": sampling["model"],
        "provider": sampling["provider"],
    }


# ===== MCP MODEL CAPABILITIES =====


@mesh.tool(
    capability="model_capabilities",
    description="Get capabilities and features of available models",
    version="1.0.0",
    tags=["mcp", "models", "capabilities", "discovery"],
)
def get_model_capabilities(
    provider: str | None = None, model: str | None = None
) -> dict[str, Any]:
    """
    Get model capabilities according to MCP specification.

    Args:
        provider: Optional filter by provider
        model: Optional filter by specific model

    Returns:
        Model capabilities information
    """

    # Mock model capabilities data (in real implementation, query actual providers)
    model_capabilities = {
        "anthropic": {
            "claude-3-sonnet-20240229": {
                "provider": "anthropic",
                "model": "claude-3-sonnet-20240229",
                "capabilities": [
                    "text_generation",
                    "conversation",
                    "analysis",
                    "coding",
                    "math",
                ],
                "max_tokens": 200000,
                "context_window": 200000,
                "supports_streaming": True,
                "supports_function_calling": True,
                "supports_vision": False,
                "pricing": {
                    "input_tokens_per_million": 3.0,
                    "output_tokens_per_million": 15.0,
                },
            },
            "claude-3-haiku-20240307": {
                "provider": "anthropic",
                "model": "claude-3-haiku-20240307",
                "capabilities": ["text_generation", "conversation", "analysis"],
                "max_tokens": 200000,
                "context_window": 200000,
                "supports_streaming": True,
                "supports_function_calling": True,
                "supports_vision": False,
                "pricing": {
                    "input_tokens_per_million": 0.25,
                    "output_tokens_per_million": 1.25,
                },
            },
        },
        "openai": {
            "gpt-4-turbo": {
                "provider": "openai",
                "model": "gpt-4-turbo",
                "capabilities": [
                    "text_generation",
                    "conversation",
                    "analysis",
                    "coding",
                    "vision",
                ],
                "max_tokens": 4096,
                "context_window": 128000,
                "supports_streaming": True,
                "supports_function_calling": True,
                "supports_vision": True,
                "pricing": {
                    "input_tokens_per_million": 10.0,
                    "output_tokens_per_million": 30.0,
                },
            }
        },
    }

    # Filter by provider if specified
    if provider:
        if provider not in model_capabilities:
            return {
                "error": f"Provider '{provider}' not found",
                "available_providers": list(model_capabilities.keys()),
            }
        model_capabilities = {provider: model_capabilities[provider]}

    # Filter by specific model if specified
    if model:
        filtered_capabilities = {}
        for prov, models in model_capabilities.items():
            if model in models:
                filtered_capabilities[prov] = {model: models[model]}

        if not filtered_capabilities:
            return {
                "error": f"Model '{model}' not found",
                "available_models": [
                    model_name
                    for provider_models in model_capabilities.values()
                    for model_name in provider_models.keys()
                ],
            }
        model_capabilities = filtered_capabilities

    return {
        "model_capabilities": model_capabilities,
        "total_providers": len(model_capabilities),
        "total_models": sum(len(models) for models in model_capabilities.values()),
        "timestamp": datetime.now().isoformat(),
    }


# ===== MCP SAMPLING WITH RESOURCES =====


@mesh.tool(
    capability="sampling_with_resources",
    description="Sampling with MCP resource integration",
    version="1.0.0",
    tags=["mcp", "sampling", "resources", "integration"],
)
def sampling_with_resources(
    messages: list[dict[str, Any]],
    resources: list[str] | None = None,
    model_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Perform sampling with MCP resource integration.

    Args:
        messages: Conversation messages
        resources: List of resource URIs to include
        model_preferences: Model preferences and hints

    Returns:
        Sampling response with resource integration
    """

    # Mock resource loading (in real implementation, load via MCP resources protocol)
    resource_content = {}
    if resources:
        for resource_uri in resources:
            # This would use MCP resources/read
            resource_content[resource_uri] = (
                f"[Mock content for resource: {resource_uri}]"
            )

    # Add resource context to messages
    enhanced_messages = messages.copy()
    if resource_content:
        resource_context = "Available resources:\n" + "\n".join(
            f"- {uri}: {content}" for uri, content in resource_content.items()
        )
        enhanced_messages.insert(0, {"role": "system", "content": resource_context})

    # Call sampling with enhanced context
    return sampling_create_message(
        messages=enhanced_messages,
        model_preferences=model_preferences,
        metadata={
            "resources_used": list(resource_content.keys()),
            "resource_count": len(resource_content),
        },
    )


# ===== SAMPLING HISTORY AND ANALYTICS =====


@mesh.tool(
    capability="sampling_analytics",
    description="Analytics and history for sampling operations",
    version="1.0.0",
    tags=["analytics", "history", "metrics"],
)
def get_sampling_analytics(
    time_range_hours: int = 24, include_details: bool = False
) -> dict[str, Any]:
    """
    Get analytics for sampling operations.

    Args:
        time_range_hours: Time range for analytics in hours
        include_details: Whether to include detailed operation info

    Returns:
        Sampling analytics and metrics
    """

    agent = LLMSamplingAgent()

    # Filter history by time range
    cutoff_time = datetime.now().timestamp() - (time_range_hours * 3600)
    recent_history = [
        entry
        for entry in agent.sampling_history
        if datetime.fromisoformat(entry["request"]["created_at"]).timestamp()
        > cutoff_time
    ]

    # Calculate analytics
    total_samplings = len(recent_history)
    successful_samplings = len(
        [h for h in recent_history if "error" not in h["response"]]
    )
    failed_samplings = total_samplings - successful_samplings

    # Model usage
    model_usage = {}
    provider_usage = {}

    for entry in recent_history:
        model = entry["request"]["model"]
        provider = entry["request"]["provider"]

        model_usage[model] = model_usage.get(model, 0) + 1
        provider_usage[provider] = provider_usage.get(provider, 0) + 1

    analytics = {
        "time_range_hours": time_range_hours,
        "total_samplings": total_samplings,
        "successful_samplings": successful_samplings,
        "failed_samplings": failed_samplings,
        "success_rate": (
            successful_samplings / total_samplings if total_samplings > 0 else 0
        ),
        "model_usage": model_usage,
        "provider_usage": provider_usage,
        "active_samplings": len(agent.active_samplings),
        "generated_at": datetime.now().isoformat(),
    }

    if include_details:
        analytics["detailed_history"] = recent_history

    return analytics


# 🎉 Official MCP Sampling Protocol implementation!
# Full compliance with MCP specification for LLM interactions!
