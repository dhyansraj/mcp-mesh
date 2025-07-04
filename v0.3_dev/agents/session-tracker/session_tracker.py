#!/usr/bin/env python3
"""
Session Tracker Agent - Session affinity management for MCP Mesh.

This agent provides session tracking and assignment capabilities:
- Session-to-pod assignment with consistent hashing
- Session lifecycle management
- Pod discovery and health tracking

Used for testing Phase 7 auto-dependency injection.
"""

import hashlib
import os

import redis
from _mcp_mesh import mesh
from fastmcp import FastMCP

# Create FastMCP server
app = FastMCP("Session Tracker Agent")

pod_ip = os.getenv("POD_IP", "localhost")
redis_url = os.getenv("REDIS_URL", "redis://redis:6379")

# Initialize Redis connection
try:
    redis_client = redis.from_url(redis_url, decode_responses=True)
    redis_client.ping()
    redis_available = True
    print(f"✅ Connected to Redis: {redis_url}")
except Exception as e:
    redis_available = False
    print(f"❌ Redis connection failed: {e}")

# In-memory fallback
session_assignments = {}


def consistent_hash(session_id: str, pods: list) -> str:
    """Use consistent hashing for session assignment."""
    if not pods:
        return pod_ip

    hash_value = int(hashlib.sha256(session_id.encode()).hexdigest(), 16)
    return pods[hash_value % len(pods)]


@app.tool()
@mesh.tool(
    capability="session_tracker",
    description="Get session assignment for session affinity",
)
def get_session_assignment(session_id: str, capability: str) -> dict:
    """Get the assigned pod for a session."""
    session_key = f"session:{session_id}:{capability}"

    # Try Redis first
    if redis_available:
        try:
            assigned_pod = redis_client.get(session_key)
            if assigned_pod:
                return {
                    "success": True,
                    "session_id": session_id,
                    "capability": capability,
                    "pod_ip": assigned_pod,
                    "source": "redis",
                    "tracker_pod": pod_ip,
                }
        except Exception as e:
            print(f"Redis get failed: {e}")

    # Fallback to memory
    if session_key in session_assignments:
        return {
            "success": True,
            "session_id": session_id,
            "capability": capability,
            "pod_ip": session_assignments[session_key],
            "source": "memory",
            "tracker_pod": pod_ip,
        }

    # Session not found
    return {
        "success": False,
        "session_id": session_id,
        "capability": capability,
        "pod_ip": None,
        "source": "not_found",
        "tracker_pod": pod_ip,
    }


@app.tool()
@mesh.tool(
    capability="session_tracker",
    description="Assign session to pod with consistent hashing",
)
def assign_session(
    session_id: str, capability: str, pod_ip: str = None, ttl: int = 3600
) -> dict:
    """Assign a session to a pod."""
    session_key = f"session:{session_id}:{capability}"

    # Use provided pod_ip or assign using consistent hashing
    if not pod_ip:
        # In a real implementation, this would discover available pods
        # For testing, just assign to current pod
        available_pods = [pod_ip]  # Would be discovered from registry
        assigned_pod = consistent_hash(session_id, available_pods)
    else:
        assigned_pod = pod_ip

    # Store in Redis
    if redis_available:
        try:
            redis_client.setex(session_key, ttl, assigned_pod)
            return {
                "success": True,
                "session_id": session_id,
                "capability": capability,
                "pod_ip": assigned_pod,
                "ttl": ttl,
                "source": "redis",
                "tracker_pod": pod_ip,
            }
        except Exception as e:
            print(f"Redis set failed: {e}")

    # Fallback to memory
    session_assignments[session_key] = assigned_pod
    return {
        "success": True,
        "session_id": session_id,
        "capability": capability,
        "pod_ip": assigned_pod,
        "ttl": ttl,
        "source": "memory",
        "tracker_pod": pod_ip,
    }


@app.tool()
@mesh.tool(capability="session_tracker", description="Remove session assignment")
def remove_session(session_id: str, capability: str) -> dict:
    """Remove a session assignment."""
    session_key = f"session:{session_id}:{capability}"

    removed_from_redis = False
    removed_from_memory = False

    # Remove from Redis
    if redis_available:
        try:
            removed_from_redis = bool(redis_client.delete(session_key))
        except Exception as e:
            print(f"Redis delete failed: {e}")

    # Remove from memory
    if session_key in session_assignments:
        del session_assignments[session_key]
        removed_from_memory = True

    return {
        "success": removed_from_redis or removed_from_memory,
        "session_id": session_id,
        "capability": capability,
        "removed_from_redis": removed_from_redis,
        "removed_from_memory": removed_from_memory,
        "tracker_pod": pod_ip,
    }


@app.tool()
@mesh.tool(capability="session_tracker", description="List all active sessions")
def list_sessions(pattern: str = "session:*") -> dict:
    """List all active sessions."""
    sessions = []

    # Get from Redis
    if redis_available:
        try:
            keys = redis_client.keys(pattern)
            for key in keys:
                value = redis_client.get(key)
                ttl = redis_client.ttl(key)
                sessions.append(
                    {
                        "session_key": key,
                        "assigned_pod": value,
                        "ttl": ttl,
                        "source": "redis",
                    }
                )
        except Exception as e:
            print(f"Redis keys failed: {e}")

    # Get from memory
    for key, value in session_assignments.items():
        if key.startswith("session:"):
            sessions.append(
                {
                    "session_key": key,
                    "assigned_pod": value,
                    "ttl": -1,  # No TTL in memory
                    "source": "memory",
                }
            )

    return {
        "success": True,
        "sessions": sessions,
        "total_sessions": len(sessions),
        "tracker_pod": pod_ip,
    }


# Health check
@app.tool()
@mesh.tool(
    capability="session_tracker_health",
    description="Health check for session tracker agent",
)
def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "pod_ip": pod_ip,
        "agent_type": "session_tracker",
        "redis_available": redis_available,
        "redis_url": redis_url,
        "memory_sessions": len(session_assignments),
        "capabilities": ["session_tracker"],
    }


if __name__ == "__main__":
    print(f"📍 Starting Session Tracker Agent on pod {pod_ip}")
    print(f"🔗 Redis URL: {redis_url}")
    print("📊 Session tracking capabilities:")
    print(
        "  - session_tracker (get_session_assignment, assign_session, remove_session, list_sessions)"
    )

    if redis_available:
        print("✅ Redis connection: OK")
    else:
        print("❌ Redis connection: FAILED (using memory fallback)")

    app.run(host="0.0.0.0", port=8080)
