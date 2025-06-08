#!/usr/bin/env python3
"""
Unified Dependency Pattern Support Example

This example demonstrates all 3 dependency patterns working simultaneously:

1. String dependencies: "legacy_auth" (existing from Week 1, Day 4)
2. Protocol interfaces: AuthService (traditional interface-based)
3. Concrete classes: OAuth2AuthService (new auto-discovery pattern)

Usage:
    python examples/unified_dependency_patterns_example.py
"""

import asyncio
import logging
from typing import Protocol, runtime_checkable

from mcp_mesh.decorators.mesh_agent import mesh_agent

# Configure logging to see the dependency resolution in action
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


# Protocol Interface Example (Pattern 2)
@runtime_checkable
class AuthService(Protocol):
    """Protocol for authentication services."""

    async def authenticate(self, token: str) -> bool:
        """Authenticate a user with the given token."""
        ...

    def get_user_id(self, token: str) -> str:
        """Get user ID from token."""
        ...


# Concrete Class Examples (Pattern 3)
class OAuth2AuthService:
    """Concrete OAuth2 authentication service."""

    def __init__(self, client_id: str = "demo_client", secret: str = "demo_secret"):
        self.client_id = client_id
        self.secret = secret
        print(f"📱 OAuth2AuthService initialized with client_id: {client_id}")

    async def authenticate(self, token: str) -> bool:
        """Authenticate using OAuth2."""
        print(f"🔐 OAuth2: Authenticating token {token[:8]}...")
        # Simulate OAuth2 validation
        valid = token.startswith("oauth2_") and len(token) > 10
        print(
            f"{'✅' if valid else '❌'} OAuth2: Authentication {'successful' if valid else 'failed'}"
        )
        return valid

    def get_user_id(self, token: str) -> str:
        """Get user ID from OAuth2 token."""
        return f"oauth2_user_{hash(token) % 1000}"

    def get_token(self) -> str:
        """Get a test token."""
        return "oauth2_demo_token_12345"


class BasicAuthService:
    """Simple concrete authentication service that implements AuthService protocol."""

    def __init__(self):
        print("🔑 BasicAuthService initialized")

    async def authenticate(self, token: str) -> bool:
        """Simple authentication."""
        print(f"🔍 Basic: Authenticating token {token[:8]}...")
        # Simple validation
        valid = token.startswith("basic_") and len(token) > 8
        print(
            f"{'✅' if valid else '❌'} Basic: Authentication {'successful' if valid else 'failed'}"
        )
        return valid

    def get_user_id(self, token: str) -> str:
        """Get user ID from basic token."""
        return f"basic_user_{hash(token) % 1000}"


class FileService:
    """File operations service."""

    def __init__(self, base_path: str = "/tmp"):
        self.base_path = base_path
        print(f"📁 FileService initialized with base_path: {base_path}")

    async def read_file(self, filename: str) -> str:
        """Read a file (simulated)."""
        print(f"📖 Reading file: {filename}")
        return f"Contents of {filename}"

    async def write_file(self, filename: str, content: str) -> bool:
        """Write a file (simulated)."""
        print(f"📝 Writing to file: {filename}")
        return True


# Example 1: All three patterns in one function
@mesh_agent(
    capabilities=["auth", "file_operations", "user_management"],
    dependencies=[
        "legacy_user_service",  # String dependency (Pattern 1)
        AuthService,  # Protocol interface (Pattern 2)
        OAuth2AuthService,  # Concrete class (Pattern 3)
    ],
    fallback_mode=True,
    enable_caching=True,
)
async def comprehensive_secure_operation(
    # These parameters will be automatically injected
    legacy_user_service: str = None,  # From string dependency
    auth_service: AuthService = None,  # From protocol dependency
    oauth2_auth: OAuth2AuthService = None,  # From concrete dependency
    # These are regular parameters
    user_token: str = "oauth2_demo_token_12345",
    operation: str = "read_profile",
):
    """
    A comprehensive function that uses all three dependency patterns.

    This demonstrates the power of unified dependency resolution:
    - Legacy string dependencies for backward compatibility
    - Protocol interfaces for flexible, testable code
    - Concrete classes for specific implementations
    """
    print("\n🚀 Starting comprehensive secure operation...")
    print(f"Operation: {operation}")
    print(f"Token: {user_token[:8]}...")

    results = {
        "operation": operation,
        "dependencies_injected": {},
        "authentication_results": {},
        "operation_successful": False,
    }

    # Check what dependencies were injected
    results["dependencies_injected"] = {
        "legacy_user_service": legacy_user_service is not None,
        "auth_service": auth_service is not None,
        "oauth2_auth": oauth2_auth is not None,
    }

    print(f"\n📋 Dependencies injected: {results['dependencies_injected']}")

    # Use the protocol interface for authentication
    if auth_service:
        print("\n🔐 Using protocol-based auth service...")
        auth_result = await auth_service.authenticate(user_token)
        results["authentication_results"]["protocol_auth"] = auth_result

        if auth_result:
            user_id = auth_service.get_user_id(user_token)
            print(f"👤 User ID from protocol auth: {user_id}")

    # Use the concrete OAuth2 service for additional verification
    if oauth2_auth:
        print("\n🔐 Using concrete OAuth2 service...")
        oauth2_result = await oauth2_auth.authenticate(user_token)
        results["authentication_results"]["oauth2_auth"] = oauth2_result

        if oauth2_result:
            user_id = oauth2_auth.get_user_id(user_token)
            print(f"👤 User ID from OAuth2: {user_id}")

    # Use legacy service (would typically be a string identifier)
    if legacy_user_service:
        print(f"\n👴 Using legacy user service: {legacy_user_service}")
        results["authentication_results"]["legacy_service"] = True

    # Determine overall success
    auth_successful = any(results["authentication_results"].values())
    results["operation_successful"] = auth_successful

    if auth_successful:
        print(f"\n✅ Operation '{operation}' completed successfully!")
        if operation == "read_profile":
            results["data"] = {"name": "Demo User", "email": "demo@example.com"}
        elif operation == "write_data":
            results["data"] = {"written": True, "timestamp": "2024-01-01T00:00:00Z"}
    else:
        print(f"\n❌ Operation '{operation}' failed - authentication required")

    return results


# Example 2: Protocol-only function
@mesh_agent(
    capabilities=["auth"],
    dependencies=[AuthService],  # Only protocol dependency
    fallback_mode=True,
)
async def protocol_only_auth(
    auth_service: AuthService = None, token: str = "basic_demo_token_456"
):
    """Function that only uses protocol-based dependencies."""
    print(f"\n🎯 Protocol-only authentication with token {token[:8]}...")

    if auth_service:
        result = await auth_service.authenticate(token)
        user_id = auth_service.get_user_id(token) if result else None
        return {"authenticated": result, "user_id": user_id}
    else:
        print("❌ No auth service available")
        return {"authenticated": False, "user_id": None}


# Example 3: Concrete-only function
@mesh_agent(
    capabilities=["file_ops"],
    dependencies=[FileService, OAuth2AuthService],  # Only concrete dependencies
    fallback_mode=True,
)
async def concrete_only_operation(
    file_service: FileService = None,
    oauth2_auth: OAuth2AuthService = None,
    filename: str = "demo.txt",
    content: str = "Hello, unified dependencies!",
):
    """Function that only uses concrete class dependencies."""
    print(f"\n🎯 Concrete-only file operation: {filename}")

    # Authenticate first
    if oauth2_auth:
        token = oauth2_auth.get_token()
        auth_result = await oauth2_auth.authenticate(token)
        if not auth_result:
            return {"success": False, "error": "Authentication failed"}

    # Perform file operation
    if file_service:
        write_result = await file_service.write_file(filename, content)
        read_result = await file_service.read_file(filename)
        return {"success": True, "written": write_result, "content": read_result}
    else:
        return {"success": False, "error": "File service not available"}


# Example 4: Legacy string-only function (backward compatibility)
@mesh_agent(
    capabilities=["legacy"],
    dependencies=["user_db", "auth_cache"],  # Only string dependencies
    fallback_mode=True,
)
async def legacy_only_operation(
    user_db=None, auth_cache=None, user_id: str = "demo_user"
):
    """Function that only uses legacy string dependencies."""
    print(f"\n🎯 Legacy-only operation for user: {user_id}")

    return {
        "user_db_available": user_db is not None,
        "auth_cache_available": auth_cache is not None,
        "user_id": user_id,
        "legacy_data": f"Data for {user_id}",
    }


async def main():
    """Main demo function."""
    print("=" * 60)
    print("🌟 UNIFIED DEPENDENCY PATTERNS DEMO")
    print("=" * 60)
    print("\nThis demo shows all 3 dependency patterns working together:")
    print("1. String dependencies (legacy)")
    print("2. Protocol interfaces (flexible)")
    print("3. Concrete classes (auto-discovery)")

    try:
        # Demo 1: All patterns together
        print("\n" + "=" * 50)
        print("📋 DEMO 1: All Three Patterns Together")
        print("=" * 50)
        result1 = await comprehensive_secure_operation(operation="read_profile")
        print(f"\n📊 Result: {result1}")

        # Demo 2: Protocol only
        print("\n" + "=" * 50)
        print("📋 DEMO 2: Protocol-Only Dependencies")
        print("=" * 50)
        result2 = await protocol_only_auth()
        print(f"\n📊 Result: {result2}")

        # Demo 3: Concrete only
        print("\n" + "=" * 50)
        print("📋 DEMO 3: Concrete-Only Dependencies")
        print("=" * 50)
        result3 = await concrete_only_operation()
        print(f"\n📊 Result: {result3}")

        # Demo 4: Legacy only
        print("\n" + "=" * 50)
        print("📋 DEMO 4: Legacy String Dependencies")
        print("=" * 50)
        result4 = await legacy_only_operation()
        print(f"\n📊 Result: {result4}")

        print("\n" + "=" * 60)
        print("✅ ALL DEMOS COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        print("\nKey Benefits Demonstrated:")
        print("• Zero configuration - no manual endpoints needed")
        print("• Backward compatibility with existing string dependencies")
        print("• Flexible protocol-based interfaces")
        print("• Auto-discovery of concrete implementations")
        print("• Seamless fallback from remote to local instances")
        print("• All patterns work simultaneously in one function")

    except Exception as e:
        print(f"\n❌ Demo failed with error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    # Run the demo
    asyncio.run(main())
