#!/usr/bin/env python3
"""
Session Agent - For testing session affinity and stateful interactions.

This agent provides capabilities that require session affinity:
- Stateful counter that maintains state per session
- User preferences that persist during a session
- Session-based conversation memory

Used for testing Phases 4-7 of the progressive implementation.
"""

import os

import mesh
from fastmcp import FastMCP

# Create FastMCP server
app = FastMCP("Session Agent")

# Global state storage (simulates per-pod state)
session_state = {}
pod_ip = os.getenv("POD_IP", "localhost")


@app.tool()
@mesh.tool(
    capability="stateful_counter",
    session_required=True,
    stateful=True,
    description="A counter that maintains state per session",
)
def increment_counter(session_id: str, increment: int = 1) -> dict:
    """Increment a counter for this session."""
    if session_id not in session_state:
        session_state[session_id] = {"counter": 0}

    session_state[session_id]["counter"] += increment

    return {
        "session_id": session_id,
        "counter": session_state[session_id]["counter"],
        "pod_ip": pod_ip,
        "message": f"Counter incremented by {increment} on pod {pod_ip}",
    }


@app.tool()
@mesh.tool(
    capability="user_preferences",
    session_required=True,
    stateful=True,
    description="Store and retrieve user preferences per session",
)
def set_preference(session_id: str, key: str, value: str) -> dict:
    """Set a user preference for this session."""
    if session_id not in session_state:
        session_state[session_id] = {"preferences": {}}

    if "preferences" not in session_state[session_id]:
        session_state[session_id]["preferences"] = {}

    session_state[session_id]["preferences"][key] = value

    return {
        "session_id": session_id,
        "pod_ip": pod_ip,
        "preference_set": {key: value},
        "all_preferences": session_state[session_id]["preferences"],
    }


@app.tool()
@mesh.tool(
    capability="user_preferences",
    session_required=True,
    stateful=True,
    description="Get user preferences for this session",
)
def get_preferences(session_id: str) -> dict:
    """Get all user preferences for this session."""
    if session_id not in session_state:
        session_state[session_id] = {"preferences": {}}

    preferences = session_state[session_id].get("preferences", {})

    return {"session_id": session_id, "pod_ip": pod_ip, "preferences": preferences}


@app.tool()
@mesh.tool(
    capability="conversation_memory",
    session_required=True,
    stateful=True,
    description="Remember conversation messages per session",
)
def add_message(session_id: str, role: str, content: str) -> dict:
    """Add a message to conversation memory."""
    if session_id not in session_state:
        session_state[session_id] = {"messages": []}

    if "messages" not in session_state[session_id]:
        session_state[session_id]["messages"] = []

    message = {
        "role": role,
        "content": content,
        "timestamp": "2025-07-03T12:00:00Z",  # Simplified timestamp
        "pod_ip": pod_ip,
    }

    session_state[session_id]["messages"].append(message)

    return {
        "session_id": session_id,
        "pod_ip": pod_ip,
        "message_added": message,
        "total_messages": len(session_state[session_id]["messages"]),
    }


@app.tool()
@mesh.tool(
    capability="conversation_memory",
    session_required=True,
    stateful=True,
    description="Get conversation history for this session",
)
def get_conversation(session_id: str) -> dict:
    """Get conversation history for this session."""
    if session_id not in session_state:
        session_state[session_id] = {"messages": []}

    messages = session_state[session_id].get("messages", [])

    return {
        "session_id": session_id,
        "pod_ip": pod_ip,
        "messages": messages,
        "total_messages": len(messages),
    }


# Health check endpoint
@app.tool()
@mesh.tool(capability="session_health", description="Health check for session agent")
def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "pod_ip": pod_ip,
        "agent_type": "session_agent",
        "active_sessions": len(session_state),
        "session_ids": list(session_state.keys()),
    }


if __name__ == "__main__":
    print(f"🔄 Starting Session Agent on pod {pod_ip}")
    print("📊 Session affinity testing capabilities:")
    print("  - stateful_counter (session_required=True)")
    print("  - user_preferences (session_required=True)")
    print("  - conversation_memory (session_required=True)")

    # Don't call app.run() - MCP Mesh runtime handles server startup
    print("🚀 MCP Mesh runtime will handle server startup")

    # Keep the script running
    import signal
    import sys

    def signal_handler(sig, frame):
        print("🛑 Graceful shutdown")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait indefinitely - MCP Mesh runtime runs the server
    signal.pause()
