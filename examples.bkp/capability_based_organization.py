#!/usr/bin/env python3
"""
Capability-Based Agent Organization Example

This example demonstrates the new single-capability-per-function pattern
that's optimized for Kubernetes deployments with hundreds of pods.

Key Concepts:
1. Each function provides exactly ONE capability
2. Functions can have multiple dependencies
3. Registry organizes by capability, not by agent
4. Scales to thousands of functions efficiently
"""

from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


def create_capability_based_server() -> FastMCP:
    """Create a server demonstrating capability-based organization."""

    # Create FastMCP server instance
    server = FastMCP(
        name="capability-demo",
        instructions="Demonstrates single capability per function pattern for Kubernetes scale.",
    )

    # ===== USER SERVICE CAPABILITIES =====
    # Each function provides ONE capability but can depend on many services

    @server.tool()
    @mesh_agent(
        capability="user_authentication",  # Single capability
        dependencies=["database_service", "crypto_service", "audit_service"],
        version="1.0.0",
        tags=["auth", "security"],
        description="Authenticates users with comprehensive security checks",
    )
    async def authenticate_user(
        username: str,
        password: str,
        database_service: Any | None = None,
        crypto_service: Any | None = None,
        audit_service: Any | None = None,
    ) -> dict[str, Any]:
        """Authenticate a user with multiple service dependencies."""

        result = {
            "username": username,
            "authenticated": False,
            "timestamp": datetime.now().isoformat(),
            "services_available": {
                "database": database_service is not None,
                "crypto": crypto_service is not None,
                "audit": audit_service is not None,
            },
        }

        if all([database_service, crypto_service, audit_service]):
            # All services available - full authentication
            try:
                # Simulate using all services
                user = await database_service.get_user(username)
                password_valid = await crypto_service.verify_password(
                    password, user.password_hash
                )
                await audit_service.log_authentication_attempt(
                    username, success=password_valid
                )

                result["authenticated"] = password_valid
                result["method"] = "full_service_authentication"
            except Exception as e:
                result["error"] = str(e)
                result["method"] = "full_service_failed"
        else:
            # Fallback mode - basic authentication
            result["authenticated"] = username == "demo" and password == "demo"
            result["method"] = "fallback_authentication"

        return result

    @server.tool()
    @mesh_agent(
        capability="user_profile",  # Different capability
        dependencies=["database_service", "cache_service"],
        version="1.0.0",
        tags=["user", "data"],
        description="Retrieves user profile information",
    )
    async def get_user_profile(
        username: str,
        database_service: Any | None = None,
        cache_service: Any | None = None,
    ) -> dict[str, Any]:
        """Get user profile with caching support."""

        profile = {
            "username": username,
            "retrieved_at": datetime.now().isoformat(),
            "source": "unknown",
        }

        # Try cache first
        if cache_service:
            try:
                cached = await cache_service.get(f"profile:{username}")
                if cached:
                    profile.update(cached)
                    profile["source"] = "cache"
                    return profile
            except Exception:
                pass

        # Try database
        if database_service:
            try:
                user_data = await database_service.get_user_profile(username)
                profile.update(user_data)
                profile["source"] = "database"

                # Update cache if available
                if cache_service:
                    await cache_service.set(f"profile:{username}", user_data, ttl=300)
            except Exception as e:
                profile["error"] = str(e)
                profile["source"] = "database_error"
        else:
            # Fallback profile
            profile.update(
                {
                    "email": f"{username}@example.com",
                    "joined": "2024-01-01",
                    "source": "fallback",
                }
            )

        return profile

    @server.tool()
    @mesh_agent(
        capability="user_permissions",  # Another distinct capability
        dependencies=["rbac_service", "database_service"],
        version="1.0.0",
        tags=["auth", "permissions"],
        description="Checks user permissions and roles",
    )
    async def check_user_permission(
        username: str,
        permission: str,
        resource: str | None = None,
        rbac_service: Any | None = None,
        database_service: Any | None = None,
    ) -> dict[str, Any]:
        """Check if user has specific permission."""

        result = {
            "username": username,
            "permission": permission,
            "resource": resource,
            "granted": False,
            "timestamp": datetime.now().isoformat(),
        }

        if rbac_service:
            try:
                # Use RBAC service for permission check
                result["granted"] = await rbac_service.has_permission(
                    username, permission, resource
                )
                result["method"] = "rbac_service"
                result["roles"] = await rbac_service.get_user_roles(username)
            except Exception as e:
                result["error"] = str(e)
                result["method"] = "rbac_failed"
        elif database_service:
            try:
                # Fallback to database lookup
                user_perms = await database_service.get_user_permissions(username)
                result["granted"] = permission in user_perms
                result["method"] = "database_lookup"
            except Exception:
                result["method"] = "database_failed"
        else:
            # Fallback logic
            result["granted"] = username == "admin" and permission == "read"
            result["method"] = "fallback_rules"

        return result

    # ===== FILE SERVICE CAPABILITIES =====
    # Separate capabilities for different file operations

    @server.tool()
    @mesh_agent(
        capability="file_read",
        dependencies=["storage_service", "security_service"],
        version="1.0.0",
        tags=["file", "storage"],
        description="Reads files with security validation",
    )
    async def read_file(
        path: str,
        storage_service: Any | None = None,
        security_service: Any | None = None,
    ) -> dict[str, Any]:
        """Read file with security checks."""

        result = {"path": path, "timestamp": datetime.now().isoformat()}

        # Security check
        if security_service:
            allowed = await security_service.check_file_access(path, "read")
            if not allowed:
                result["error"] = "Access denied"
                return result

        # Read file
        if storage_service:
            try:
                content = await storage_service.read(path)
                result["content"] = content
                result["size"] = len(content)
                result["source"] = "storage_service"
            except Exception as e:
                result["error"] = str(e)
        else:
            # Fallback
            result["content"] = f"Simulated content of {path}"
            result["source"] = "fallback"

        return result

    @server.tool()
    @mesh_agent(
        capability="file_write",
        dependencies=["storage_service", "security_service", "audit_service"],
        version="1.0.0",
        tags=["file", "storage"],
        description="Writes files with security validation and audit",
    )
    async def write_file(
        path: str,
        content: str,
        storage_service: Any | None = None,
        security_service: Any | None = None,
        audit_service: Any | None = None,
    ) -> dict[str, Any]:
        """Write file with security and audit."""

        result = {"path": path, "timestamp": datetime.now().isoformat()}

        # Security check
        if security_service:
            allowed = await security_service.check_file_access(path, "write")
            if not allowed:
                result["error"] = "Access denied"
                return result

        # Write file
        if storage_service:
            try:
                await storage_service.write(path, content)
                result["success"] = True
                result["bytes_written"] = len(content)
                result["method"] = "storage_service"

                # Audit the write
                if audit_service:
                    await audit_service.log_file_operation("write", path, len(content))
            except Exception as e:
                result["error"] = str(e)
                result["success"] = False
        else:
            # Fallback
            result["success"] = True
            result["method"] = "fallback_simulation"

        return result

    # ===== MONITORING CAPABILITIES =====

    @server.tool()
    @mesh_agent(
        capability="health_check",
        dependencies=["monitoring_service", "database_service"],
        version="1.0.0",
        tags=["monitoring", "health"],
        description="Performs comprehensive health checks",
    )
    async def check_system_health(
        monitoring_service: Any | None = None, database_service: Any | None = None
    ) -> dict[str, Any]:
        """Check overall system health."""

        health = {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "healthy",
            "checks": {},
        }

        # Check monitoring service
        if monitoring_service:
            try:
                metrics = await monitoring_service.get_system_metrics()
                health["checks"]["monitoring"] = {
                    "status": "healthy",
                    "metrics": metrics,
                }
            except Exception as e:
                health["checks"]["monitoring"] = {
                    "status": "unhealthy",
                    "error": str(e),
                }
                health["overall_status"] = "degraded"

        # Check database
        if database_service:
            try:
                db_health = await database_service.health_check()
                health["checks"]["database"] = db_health
            except Exception as e:
                health["checks"]["database"] = {"status": "unhealthy", "error": str(e)}
                health["overall_status"] = "degraded"

        # If no services available
        if not monitoring_service and not database_service:
            health["checks"]["fallback"] = {
                "status": "healthy",
                "message": "No services to check, assuming healthy",
            }

        return health

    # ===== CAPABILITY DISCOVERY =====

    @server.tool()
    def list_capabilities() -> dict[str, Any]:
        """List all capabilities provided by this server."""

        capabilities = {
            "user_service": ["user_authentication", "user_profile", "user_permissions"],
            "file_service": ["file_read", "file_write"],
            "monitoring_service": ["health_check"],
            "benefits": [
                "Each function provides ONE capability",
                "Easy to scale in Kubernetes (one pod per capability)",
                "Registry organizes by capability tree",
                "Efficient capability-based discovery",
                "Clear separation of concerns",
            ],
            "kubernetes_deployment": {
                "user_auth_pod": ["user_authentication"],
                "user_data_pod": ["user_profile", "user_permissions"],
                "file_pod": ["file_read", "file_write"],
                "monitoring_pod": ["health_check"],
            },
        }

        return capabilities

    return server


def main():
    """Run the capability-based organization demo server."""
    import signal
    import sys

    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully."""
        print(f"\n📍 Received signal {signum}")
        print("🛑 Shutting down gracefully...")
        sys.exit(0)

    # Install signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("🚀 Starting Capability-Based Organization Demo Server...")

    # Create the server
    server = create_capability_based_server()

    print(f"📡 Server name: {server.name}")
    print("\n🎯 Capability Organization:")
    print("• One capability per function (Kubernetes-optimized)")
    print("• Multiple dependencies per function supported")
    print("• Registry organizes by capability tree")
    print("\n📋 Available Capabilities:")
    print("• user_authentication - Authenticate users")
    print("• user_profile - Get user profiles")
    print("• user_permissions - Check permissions")
    print("• file_read - Read files")
    print("• file_write - Write files")
    print("• health_check - System health monitoring")
    print("\n💡 Benefits:")
    print("• Scales to 1000s of functions efficiently")
    print("• Natural Kubernetes pod organization")
    print("• O(1) capability lookups in registry")
    print("• Clear capability ownership")
    print("\n📝 Server ready on stdio transport...")
    print("🛑 Press Ctrl+C to stop.\n")

    # Run the server with stdio transport
    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user.")
    except Exception as e:
        print(f"❌ Server error: {e}")


if __name__ == "__main__":
    main()
