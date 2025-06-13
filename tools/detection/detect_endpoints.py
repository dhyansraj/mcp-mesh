#!/usr/bin/env python3
"""
Dual-Contract Endpoint Detection Tool

Scans codebase for HTTP endpoints and validates them against appropriate OpenAPI specs.
Supports both Registry API and Agent API contracts.

🤖 AI BEHAVIOR GUIDANCE:
This tool ensures endpoints exist in the CORRECT OpenAPI specification:
- Registry code should match: api/mcp-mesh-registry.openapi.yaml
- Agent code should match: api/mcp-mesh-agent.openapi.yaml

IF THIS TOOL FINDS EXTRA ENDPOINTS:
- Check which service they belong to (registry vs agent)
- Add to appropriate OpenAPI spec
- If unsure, ask user for clarification

NEVER bypass this check by modifying the tool.
"""

import re
import sys
from pathlib import Path

import yaml


class DualContractEndpointDetector:
    """Detects HTTP endpoints and validates against appropriate contracts."""

    def __init__(
        self, registry_spec_path: str, agent_spec_path: str, source_paths: list[str]
    ):
        self.registry_spec_path = Path(registry_spec_path)
        self.agent_spec_path = Path(agent_spec_path)
        self.source_paths = [Path(p) for p in source_paths]
        self.registry_endpoints = self._load_openapi_endpoints(
            self.registry_spec_path, "Registry"
        )
        self.agent_endpoints = self._load_openapi_endpoints(
            self.agent_spec_path, "Agent"
        )

    def _load_openapi_endpoints(
        self, spec_path: Path, spec_name: str
    ) -> set[tuple[str, str]]:
        """Load endpoints from OpenAPI specification."""
        endpoints = set()

        if not spec_path.exists():
            print(f"Warning: {spec_name} OpenAPI spec not found: {spec_path}")
            return endpoints

        with open(spec_path) as f:
            spec = yaml.safe_load(f)

        paths = spec.get("paths", {})
        for path, methods in paths.items():
            for method in methods.keys():
                if method.upper() in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
                    endpoints.add((method.upper(), path))

        return endpoints

    def scan_go_files(self) -> set[tuple[str, str]]:
        """Scan Go files for HTTP endpoints."""
        endpoints = set()

        # Patterns for Gin/Echo/etc. HTTP handlers - only paths starting with /
        patterns = [
            r'\.(?P<method>GET|POST|PUT|DELETE|PATCH)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
            r'router\.(?P<method>GET|POST|PUT|DELETE|PATCH)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
            r'engine\.(?P<method>GET|POST|PUT|DELETE|PATCH)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
            r'group\.(?P<method>GET|POST|PUT|DELETE|PATCH)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
        ]

        for source_path in self.source_paths:
            if not source_path.exists():
                continue

            for go_file in source_path.rglob("*.go"):
                # Skip generated files, mocks, and deprecated files
                if (
                    "generated" in str(go_file)
                    or "mock" in str(go_file)
                    or "deprecated" in str(go_file)
                    or "_old_" in str(go_file)
                ):
                    continue

                content = go_file.read_text()

                for pattern in patterns:
                    for match in re.finditer(pattern, content):
                        method = match.group("method")
                        path = match.group("path")
                        endpoints.add((method, path))
                        print(f"Found Go endpoint: {method} {path} in {go_file}")

        return endpoints

    def scan_python_files(self) -> set[tuple[str, str]]:
        """Scan Python files for HTTP endpoints."""
        endpoints = set()

        # Patterns for Flask/FastAPI/etc. HTTP handlers - only paths starting with /
        patterns = [
            r'@app\.(?P<method>get|post|put|delete|patch)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
            r'@router\.(?P<method>get|post|put|delete|patch)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
            r'app\.(?P<method>get|post|put|delete|patch)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
            r'router\.(?P<method>get|post|put|delete|patch)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
            # AsyncHTTP and aiohttp patterns
            r'client\.(?P<method>get|post|put|delete|patch)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
            r'session\.(?P<method>get|post|put|delete|patch)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
        ]

        for source_path in self.source_paths:
            if not source_path.exists():
                continue

            for py_file in source_path.rglob("*.py"):
                # Skip generated files, tests, mocks, and deprecated files
                if (
                    "generated" in str(py_file)
                    or "mock" in str(py_file)
                    or "test" in str(py_file)
                    or "deprecated" in str(py_file)
                    or "_old_" in str(py_file)
                ):
                    continue

                content = py_file.read_text()

                for pattern in patterns:
                    for match in re.finditer(pattern, content, re.IGNORECASE):
                        method = match.group("method").upper()
                        path = match.group("path")
                        endpoints.add((method, path))
                        print(f"Found Python endpoint: {method} {path} in {py_file}")

        return endpoints

    def detect_registry_endpoints(self) -> set[tuple[str, str]]:
        """Detect endpoints in registry Go code."""
        registry_endpoints = set()

        for source_path in self.source_paths:
            if not source_path.exists():
                continue

            # Only scan registry paths for Go endpoints
            if "registry" in str(source_path).lower():
                for go_file in source_path.rglob("*.go"):
                    if (
                        "generated" in str(go_file)
                        or "mock" in str(go_file)
                        or "deprecated" in str(go_file)
                        or "_old_" in str(go_file)
                    ):
                        continue

                    content = go_file.read_text()
                    patterns = [
                        r'\.(?P<method>GET|POST|PUT|DELETE|PATCH)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
                        r'router\.(?P<method>GET|POST|PUT|DELETE|PATCH)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
                        r'engine\.(?P<method>GET|POST|PUT|DELETE|PATCH)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
                    ]

                    for pattern in patterns:
                        for match in re.finditer(pattern, content):
                            method = match.group("method")
                            path = match.group("path")
                            registry_endpoints.add((method, path))
                            print(
                                f"Found Registry endpoint: {method} {path} in {go_file}"
                            )

        return registry_endpoints

    def detect_agent_endpoints(self) -> set[tuple[str, str]]:
        """Detect endpoints in agent Python code."""
        agent_endpoints = set()

        for source_path in self.source_paths:
            if not source_path.exists():
                continue

            # Only scan agent/runtime paths for Python endpoints
            if any(
                term in str(source_path).lower()
                for term in ["runtime", "agent", "http_wrapper"]
            ):
                for py_file in source_path.rglob("*.py"):
                    if (
                        "generated" in str(py_file)
                        or "mock" in str(py_file)
                        or "test" in str(py_file)
                        or "deprecated" in str(py_file)
                        or "_old_" in str(py_file)
                    ):
                        continue

                    content = py_file.read_text()
                    patterns = [
                        r'@app\.(?P<method>get|post|put|delete|patch)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
                        r'@router\.(?P<method>get|post|put|delete|patch)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
                        r'app\.(?P<method>get|post|put|delete|patch)\s*\(\s*["\'](?P<path>/[^"\']*)["\']',
                    ]

                    for pattern in patterns:
                        for match in re.finditer(pattern, content, re.IGNORECASE):
                            method = match.group("method").upper()
                            path = match.group("path")
                            agent_endpoints.add((method, path))
                            print(f"Found Agent endpoint: {method} {path} in {py_file}")

        return agent_endpoints

    def validate_dual_contracts(self) -> bool:
        """Validate endpoints against appropriate contracts."""
        registry_code_endpoints = self.detect_registry_endpoints()
        agent_code_endpoints = self.detect_agent_endpoints()

        # Check registry endpoints
        extra_registry_endpoints = registry_code_endpoints - self.registry_endpoints

        # Check agent endpoints
        extra_agent_endpoints = agent_code_endpoints - self.agent_endpoints

        success = True

        if extra_registry_endpoints:
            print("❌ Found Registry endpoints not in Registry OpenAPI specification:")
            for method, path in extra_registry_endpoints:
                print(f"  {method} {path}")
            print("\nTo fix Registry endpoints:")
            print("1. Add missing endpoints to api/mcp-mesh-registry.openapi.yaml")
            print("2. Or remove manual endpoint implementations")
            print("3. Run 'make generate' after updating spec")
            print()
            success = False

        if extra_agent_endpoints:
            print("❌ Found Agent endpoints not in Agent OpenAPI specification:")
            for method, path in extra_agent_endpoints:
                print(f"  {method} {path}")
            print("\nTo fix Agent endpoints:")
            print("1. Add missing endpoints to api/mcp-mesh-agent.openapi.yaml")
            print("2. Or remove manual endpoint implementations")
            print("3. Run 'make generate' after updating spec")
            print()
            success = False

        if success:
            print("✅ All endpoints are defined in appropriate OpenAPI specifications")
            print(
                f"  Registry endpoints: {len(registry_code_endpoints)} found, all valid"
            )
            print(f"  Agent endpoints: {len(agent_code_endpoints)} found, all valid")

        return success


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: detect_endpoints.py <registry_spec> <agent_spec> [source_path1] [source_path2] ..."
        )
        print(
            "Example: detect_endpoints.py api/mcp-mesh-registry.openapi.yaml api/mcp-mesh-agent.openapi.yaml src"
        )
        sys.exit(1)

    registry_spec_path = sys.argv[1]
    agent_spec_path = sys.argv[2]
    source_paths = sys.argv[3:] if len(sys.argv) > 3 else ["src"]

    detector = DualContractEndpointDetector(
        registry_spec_path, agent_spec_path, source_paths
    )

    if detector.validate_dual_contracts():
        print("Dual-contract endpoint validation passed")
        sys.exit(0)
    else:
        print("Dual-contract endpoint validation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
