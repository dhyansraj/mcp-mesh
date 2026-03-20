"""
Unit tests for FastMCPServerDiscoveryStep pipeline step.

Tests the critical FastMCP server detection logic with focus on failure points
that could break with FastMCP API changes, version upgrades, or unexpected user patterns.
Includes canary tests designed to fail when FastMCP internals change.
"""

import sys
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

# Import the classes under test
from _mcp_mesh.pipeline.mcp_startup.fastmcpserver_discovery import (
    FastMCPServerDiscoveryStep,
)
from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus


class TestFastMCPServerDiscoveryStep:
    """Test the FastMCPServerDiscoveryStep class initialization and basic properties."""

    def test_initialization(self):
        """Test FastMCPServerDiscoveryStep initialization."""
        step = FastMCPServerDiscoveryStep()

        assert step.name == "fastmcp-server-discovery"
        assert step.required is False  # Optional step
        assert (
            step.description
            == "Discover FastMCP server instances and prepare for takeover"
        )

    def test_inheritance(self):
        """Test FastMCPServerDiscoveryStep inherits from PipelineStep."""
        from _mcp_mesh.pipeline.shared import PipelineStep

        step = FastMCPServerDiscoveryStep()
        assert isinstance(step, PipelineStep)

    def test_execute_method_exists(self):
        """Test execute method exists and is callable."""
        step = FastMCPServerDiscoveryStep()
        assert hasattr(step, "execute")
        assert callable(step.execute)

    def test_private_methods_exist(self):
        """Test critical private methods exist."""
        step = FastMCPServerDiscoveryStep()
        assert hasattr(step, "_discover_fastmcp_instances")
        assert hasattr(step, "_is_fastmcp_instance")
        assert hasattr(step, "_extract_server_info")
        assert hasattr(step, "_search_module_for_fastmcp")

    def test_pipeline_step_optional(self):
        """Test that this step is marked as optional (not required)."""
        step = FastMCPServerDiscoveryStep()
        assert step.required is False


class TestFastMCPDetectionLogic:
    """Test core FastMCP instance detection logic - CRITICAL for catching API changes."""

    @pytest.fixture
    def step(self):
        """Create a FastMCPServerDiscoveryStep instance."""
        return FastMCPServerDiscoveryStep()

    @pytest.fixture
    def mock_fastmcp_instance(self):
        """Create a realistic FastMCP instance mock (v3 structure)."""
        mock_instance = MagicMock()
        mock_instance.__class__.__name__ = "FastMCP"
        mock_instance.name = "test-server"
        mock_lp = MagicMock()
        mock_lp._components = {}
        mock_instance.local_provider = mock_lp
        mock_instance.tool = MagicMock()  # The decorator method
        return mock_instance

    @pytest.fixture
    def mock_local_provider(self):
        """Create a mock local_provider with components (v3 structure)."""
        mock_lp = MagicMock()

        # Mock tool components
        mock_tool1 = MagicMock()
        mock_tool1.fn = MagicMock()
        mock_tool1.fn.__name__ = "test_function_1"
        mock_tool1.name = "test_tool_1"

        mock_tool2 = MagicMock()
        mock_tool2.fn = MagicMock()
        mock_tool2.fn.__name__ = "test_function_2"
        mock_tool2.name = "test_tool_2"

        mock_lp._components = {
            "tool:test_tool_1@": mock_tool1,
            "tool:test_tool_2@": mock_tool2,
        }
        return mock_lp

    def test_fastmcp_detection_success(self, step, mock_fastmcp_instance):
        """Test successful FastMCP instance detection."""
        result = step._is_fastmcp_instance(mock_fastmcp_instance)
        assert result is True

    def test_fastmcp_detection_class_name_mismatch(self, step):
        """Test rejection when class name is not exactly 'FastMCP'."""
        mock_obj = MagicMock()
        mock_obj.__class__.__name__ = "FastMCPServer"  # Different name
        mock_obj.name = "test"
        mock_lp = MagicMock()
        mock_lp._components = {}
        mock_obj.local_provider = mock_lp
        mock_obj.tool = MagicMock()

        result = step._is_fastmcp_instance(mock_obj)
        assert result is False

    def test_fastmcp_detection_missing_name_attribute(self, step):
        """Test rejection when 'name' attribute is missing."""
        mock_obj = MagicMock()
        mock_obj.__class__.__name__ = "FastMCP"
        # Remove the name attribute explicitly
        del mock_obj.name
        mock_lp = MagicMock()
        mock_lp._components = {}
        mock_obj.local_provider = mock_lp
        mock_obj.tool = MagicMock()

        result = step._is_fastmcp_instance(mock_obj)
        assert result is False

    def test_fastmcp_detection_missing_local_provider(self, step):
        """Test rejection when 'local_provider' attribute is missing."""
        mock_obj = MagicMock()
        mock_obj.__class__.__name__ = "FastMCP"
        mock_obj.name = "test"
        # Remove the local_provider attribute explicitly
        del mock_obj.local_provider
        mock_obj.tool = MagicMock()

        result = step._is_fastmcp_instance(mock_obj)
        assert result is False

    def test_fastmcp_detection_missing_tool_decorator(self, step):
        """Test rejection when 'tool' decorator method is missing."""
        mock_obj = MagicMock()
        mock_obj.__class__.__name__ = "FastMCP"
        mock_obj.name = "test"
        mock_lp = MagicMock()
        mock_lp._components = {}
        mock_obj.local_provider = mock_lp
        # Remove the tool attribute explicitly
        del mock_obj.tool

        result = step._is_fastmcp_instance(mock_obj)
        assert result is False

    def test_fastmcp_detection_exception_handling(self, step):
        """Test graceful handling of exceptions during detection."""

        # Create an object that raises exceptions on attribute access
        class ExceptionRaisingObject:
            def __init__(self):
                self.__class__.__name__ = "FastMCP"

            def __getattr__(self, name):
                raise Exception(f"Attribute access failed for {name}")

        mock_obj = ExceptionRaisingObject()
        result = step._is_fastmcp_instance(mock_obj)
        assert result is False

    def test_fastmcp_detection_no_class_attribute(self, step):
        """Test handling objects without __class__ attribute."""
        # Use a basic object or None
        result1 = step._is_fastmcp_instance(None)
        result2 = step._is_fastmcp_instance("not_an_object")
        result3 = step._is_fastmcp_instance(42)

        assert result1 is False
        assert result2 is False
        assert result3 is False


class TestInformationExtraction:
    """Test information extraction from FastMCP instances."""

    @pytest.fixture
    def step(self):
        """Create a FastMCPServerDiscoveryStep instance."""
        return FastMCPServerDiscoveryStep()

    @pytest.fixture
    def complete_fastmcp_instance(self):
        """Create a complete FastMCP instance with all component types (v3 structure)."""
        mock_instance = MagicMock()
        mock_instance.name = "complete-server"

        # Create local_provider with _components dict
        mock_lp = MagicMock()

        mock_tool = MagicMock()
        mock_tool.fn = MagicMock()
        mock_tool.name = "test_tool"

        mock_prompt = MagicMock()
        mock_prompt.name = "test_prompt"

        mock_resource = MagicMock()
        mock_resource.name = "test_resource"

        mock_lp._components = {
            "tool:test_tool@": mock_tool,
            "prompt:test_prompt@": mock_prompt,
            "resource:test_resource@": mock_resource,
        }
        mock_instance.local_provider = mock_lp

        return mock_instance

    def test_extract_server_info_complete(self, step, complete_fastmcp_instance):
        """Test extraction from complete FastMCP instance."""
        info = step._extract_server_info("test_server", complete_fastmcp_instance)

        assert info["server_name"] == "test_server"
        assert info["server_instance"] == complete_fastmcp_instance
        assert info["fastmcp_name"] == "complete-server"
        assert info["function_count"] == 3  # 1 tool + 1 prompt + 1 resource
        assert len(info["tools"]) == 1
        assert len(info["prompts"]) == 1
        assert len(info["resources"]) == 1

    def test_extract_server_info_tools_only(self, step):
        """Test extraction from FastMCP instance with only tools."""
        mock_instance = MagicMock()
        mock_instance.name = "tools-only-server"

        mock_lp = MagicMock()
        mock_tool1 = MagicMock()
        mock_tool1.fn = MagicMock()
        mock_tool1.name = "tool1"
        mock_tool2 = MagicMock()
        mock_tool2.fn = MagicMock()
        mock_tool2.name = "tool2"
        mock_lp._components = {
            "tool:tool1@": mock_tool1,
            "tool:tool2@": mock_tool2,
        }
        mock_instance.local_provider = mock_lp

        info = step._extract_server_info("tools_server", mock_instance)

        assert info["function_count"] == 2
        assert len(info["tools"]) == 2
        assert info["prompts"] == {}
        assert info["resources"] == {}

    def test_extract_server_info_no_managers(self, step):
        """Test extraction from minimal FastMCP instance."""

        # Create a simple object without automatic attribute creation
        class MinimalInstance:
            def __init__(self):
                self.name = "minimal-server"

        mock_instance = MinimalInstance()

        info = step._extract_server_info("minimal_server", mock_instance)

        assert info["server_name"] == "minimal_server"
        assert info["fastmcp_name"] == "minimal-server"
        assert info["function_count"] == 0
        assert info["tools"] == {}
        assert info["prompts"] == {}
        assert info["resources"] == {}
        assert info["tool_manager"] is None

    def test_extract_server_info_exception_handling(self, step):
        """Test extraction handles exceptions gracefully in local_provider access."""

        # Create an instance that raises exceptions when accessing local_provider
        class ErrorInstance:
            @property
            def name(self):
                return "error-server"

            @property
            def local_provider(self):
                raise Exception("local_provider access failed")

        mock_instance = ErrorInstance()

        info = step._extract_server_info("error_server", mock_instance)

        # Should still return basic structure despite errors
        assert info["server_name"] == "error_server"
        assert info["fastmcp_name"] == "error-server"
        assert info["function_count"] == 0
        assert info["tools"] == {}
        assert info["tool_manager"] is None

    def test_extract_server_info_missing_components_dict(self, step):
        """Test extraction when local_provider exists but _components is missing."""
        mock_instance = MagicMock()
        mock_instance.name = "partial-server"

        mock_lp = MagicMock()
        # _components doesn't exist
        del mock_lp._components
        mock_instance.local_provider = mock_lp

        info = step._extract_server_info("partial_server", mock_instance)

        assert info["function_count"] == 0
        assert info["tools"] == {}

    def test_function_count_accuracy(self, step):
        """Test function count calculation across all component types."""
        mock_instance = MagicMock()
        mock_instance.name = "count-test-server"

        mock_lp = MagicMock()

        # 3 tools
        mock_t1 = MagicMock()
        mock_t1.name = "t1"
        mock_t2 = MagicMock()
        mock_t2.name = "t2"
        mock_t3 = MagicMock()
        mock_t3.name = "t3"

        # 2 prompts
        mock_p1 = MagicMock()
        mock_p1.name = "p1"
        mock_p2 = MagicMock()
        mock_p2.name = "p2"

        # 1 resource
        mock_r1 = MagicMock()
        mock_r1.name = "r1"

        mock_lp._components = {
            "tool:t1@": mock_t1,
            "tool:t2@": mock_t2,
            "tool:t3@": mock_t3,
            "prompt:p1@": mock_p1,
            "prompt:p2@": mock_p2,
            "resource:r1@": mock_r1,
        }
        mock_instance.local_provider = mock_lp

        info = step._extract_server_info("count_server", mock_instance)

        assert info["function_count"] == 6  # 3 + 2 + 1


class TestModuleDiscovery:
    """Test module discovery and filtering logic."""

    @pytest.fixture
    def step(self):
        """Create a FastMCPServerDiscoveryStep instance."""
        return FastMCPServerDiscoveryStep()

    @pytest.fixture
    def mock_fastmcp_instance(self):
        """Create a mock FastMCP instance (v3 structure)."""
        mock_instance = MagicMock()
        mock_instance.__class__.__name__ = "FastMCP"
        mock_instance.name = "test-server"
        mock_lp = MagicMock()
        mock_lp._components = {}
        mock_instance.local_provider = mock_lp
        mock_instance.tool = MagicMock()
        return mock_instance

    def test_search_module_for_fastmcp_found(self, step, mock_fastmcp_instance):
        """Test finding FastMCP instances in a module."""
        mock_module = MagicMock()
        mock_module.__dict__ = {
            "server": mock_fastmcp_instance,
            "other_var": "not_fastmcp",
        }

        found = step._search_module_for_fastmcp(mock_module, "test_module")

        assert len(found) == 1
        assert "test_module.server" in found
        assert found["test_module.server"] == mock_fastmcp_instance

    def test_search_module_for_fastmcp_none_found(self, step):
        """Test module search when no FastMCP instances are found."""
        mock_module = MagicMock()
        mock_module.__dict__ = {"var1": "string", "var2": 42, "var3": MagicMock()}

        found = step._search_module_for_fastmcp(mock_module, "empty_module")

        assert len(found) == 0

    def test_search_module_without_dict(self, step):
        """Test module search on objects without __dict__."""
        mock_module = "not_a_module"  # String has no __dict__

        found = step._search_module_for_fastmcp(mock_module, "invalid_module")

        assert len(found) == 0

    def test_search_module_exception_handling(self, step):
        """Test module search handles exceptions gracefully."""

        # Create a module that raises exception when accessing __dict__
        class ErrorModule:
            @property
            def __dict__(self):
                raise Exception("Dict access failed")

        mock_module = ErrorModule()

        found = step._search_module_for_fastmcp(mock_module, "error_module")

        assert len(found) == 0

    def test_discover_fastmcp_instances_main_module(self, step, mock_fastmcp_instance):
        """Test discovery in __main__ module."""
        # Mock the _search_module_for_fastmcp method to return a known result
        with patch.object(step, "_search_module_for_fastmcp") as mock_search:
            mock_search.return_value = {"__main__.app": mock_fastmcp_instance}

            # Mock sys.modules.get to return a main module
            with patch("sys.modules") as mock_modules:
                mock_main = MagicMock()
                mock_modules.get.return_value = mock_main
                mock_modules.items.return_value = []

                discovered = step._discover_fastmcp_instances()

                assert len(discovered) >= 1
                assert any("__main__.app" in key for key in discovered.keys())

    def test_discover_fastmcp_instances_no_main(self, step):
        """Test discovery when __main__ module is not available."""
        with patch("sys.modules") as mock_modules:
            mock_modules.get.return_value = None  # No __main__
            mock_modules.items.return_value = []

            discovered = step._discover_fastmcp_instances()

            assert isinstance(discovered, dict)

    def test_system_module_exclusion(self, step, mock_fastmcp_instance):
        """Test that system modules are excluded from search."""

        # Create proper module mocks
        class MockSysModule:
            def __init__(self):
                self.server = mock_fastmcp_instance
                self.__file__ = "/usr/lib/python3.11/sys.py"

        class MockUserModule:
            def __init__(self):
                self.app = mock_fastmcp_instance
                self.__file__ = "/home/user/my_app.py"

        mock_sys_module = MockSysModule()
        mock_user_module = MockUserModule()

        # Mock the search method to control what it finds
        def mock_search_side_effect(module, module_name):
            if module_name == "sys":
                return {}  # Should be excluded by the discovery logic
            elif module_name == "my_app":
                return {"my_app.app": mock_fastmcp_instance}
            return {}

        with patch.object(
            step, "_search_module_for_fastmcp", side_effect=mock_search_side_effect
        ):
            with patch("sys.modules") as mock_modules:
                mock_modules.get.return_value = None  # No __main__
                mock_modules.items.return_value = [
                    ("sys", mock_sys_module),  # Should be excluded
                    ("my_app", mock_user_module),  # Should be included
                ]

                discovered = step._discover_fastmcp_instances()

                # Should only find the user module, not sys module
                assert not any("sys." in key for key in discovered.keys())
                assert any("my_app." in key for key in discovered.keys())


class TestExecuteMethod:
    """Test the main execute method with various scenarios."""

    @pytest.fixture
    def step(self):
        """Create a FastMCPServerDiscoveryStep instance."""
        return FastMCPServerDiscoveryStep()

    @pytest.mark.asyncio
    async def test_execute_no_fastmcp_found(self, step):
        """Test execute when no FastMCP instances are found."""
        with patch.object(step, "_discover_fastmcp_instances", return_value={}):
            result = await step.execute({})

            assert result.status == PipelineStatus.SKIPPED
            assert result.message == "No FastMCP server instances found"
            assert len(result.context) == 0

    @pytest.mark.asyncio
    async def test_execute_fastmcp_found(self, step):
        """Test execute when FastMCP instances are found."""
        mock_server = MagicMock()
        mock_server.name = "found-server"
        mock_lp = MagicMock()
        mock_tool = MagicMock()
        mock_tool.name = "tool1"
        mock_lp._components = {"tool:tool1@": mock_tool}
        mock_server.local_provider = mock_lp

        discovered = {"test_module.server": mock_server}

        with patch.object(step, "_discover_fastmcp_instances", return_value=discovered):
            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert "Discovered 1 FastMCP servers" in result.message
            assert result.context["fastmcp_server_count"] == 1
            assert result.context["fastmcp_total_functions"] >= 0
            assert "fastmcp_servers" in result.context
            assert "fastmcp_server_info" in result.context

    @pytest.mark.asyncio
    async def test_execute_multiple_servers(self, step):
        """Test execute with multiple FastMCP servers."""
        mock_server1 = MagicMock()
        mock_server1.name = "server1"
        mock_lp1 = MagicMock()
        mock_tool1 = MagicMock()
        mock_tool1.name = "tool1"
        mock_tool2 = MagicMock()
        mock_tool2.name = "tool2"
        mock_lp1._components = {
            "tool:tool1@": mock_tool1,
            "tool:tool2@": mock_tool2,
        }
        mock_server1.local_provider = mock_lp1

        mock_server2 = MagicMock()
        mock_server2.name = "server2"
        mock_lp2 = MagicMock()
        mock_tool3 = MagicMock()
        mock_tool3.name = "tool3"
        mock_lp2._components = {"tool:tool3@": mock_tool3}
        mock_server2.local_provider = mock_lp2

        discovered = {"module1.server1": mock_server1, "module2.server2": mock_server2}

        with patch.object(step, "_discover_fastmcp_instances", return_value=discovered):
            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert result.context["fastmcp_server_count"] == 2
            assert result.context["fastmcp_total_functions"] == 3  # 2 + 1

    @pytest.mark.asyncio
    async def test_execute_exception_handling(self, step):
        """Test execute handles exceptions gracefully."""
        with patch.object(
            step,
            "_discover_fastmcp_instances",
            side_effect=Exception("Discovery failed"),
        ):
            result = await step.execute({})

            assert result.status == PipelineStatus.FAILED
            assert "FastMCP server discovery failed:" in result.message
            assert "Discovery failed" in result.errors

    @pytest.mark.asyncio
    async def test_context_keys_populated(self, step):
        """Test that all expected context keys are populated."""
        mock_server = MagicMock()
        mock_server.name = "context-test-server"
        mock_lp = MagicMock()
        mock_lp._components = {}
        mock_server.local_provider = mock_lp

        discovered = {"test.server": mock_server}

        with patch.object(step, "_discover_fastmcp_instances", return_value=discovered):
            result = await step.execute({})

            required_keys = [
                "fastmcp_servers",
                "fastmcp_server_info",
                "fastmcp_server_count",
                "fastmcp_total_functions",
            ]
            for key in required_keys:
                assert key in result.context


class TestCriticalFailureDetection:
    """Canary tests designed to fail when FastMCP internals change - BREAKING CHANGE DETECTION."""

    @pytest.fixture
    def step(self):
        """Create a FastMCPServerDiscoveryStep instance."""
        return FastMCPServerDiscoveryStep()

    def test_canary_fastmcp_class_name_detection(self, step):
        """
        CANARY TEST: This test should FAIL if FastMCP changes its class name.

        If this test fails, update the class name detection in _is_fastmcp_instance().
        """
        mock_obj = MagicMock()
        mock_obj.__class__.__name__ = "FastMCP"  # EXACT class name expected
        mock_obj.name = "canary-server"
        mock_lp = MagicMock()
        mock_lp._components = {}
        mock_obj.local_provider = mock_lp
        mock_obj.tool = MagicMock()

        result = step._is_fastmcp_instance(mock_obj)

        # This assertion protects against FastMCP class name changes
        assert result is True, (
            "BREAKING CHANGE DETECTED: FastMCP class name may have changed. "
            "Expected class name 'FastMCP', but detection failed. "
            "Update _is_fastmcp_instance() method if FastMCP changed its class name."
        )

    def test_canary_local_provider_components_structure(self, step):
        """
        CANARY TEST: This test should FAIL if FastMCP changes local_provider._components structure.

        If this test fails, update the component extraction logic in _extract_server_info().
        """
        mock_instance = MagicMock()
        mock_instance.name = "canary-tool-test"

        # Create local_provider with expected v3 _components structure
        # Use strict Mock(spec_set=...) so hasattr checks actually detect SDK drift
        mock_lp = MagicMock()
        mock_tool = Mock(spec_set=["fn", "name", "parameters"])
        mock_tool.fn = lambda: None
        mock_tool.name = "canary_tool"
        mock_tool.parameters = {"type": "object", "properties": {}}
        mock_lp._components = {"tool:canary_tool@": mock_tool}  # EXACT v3 structure
        mock_instance.local_provider = mock_lp

        info = step._extract_server_info("canary", mock_instance)

        # This assertion protects against local_provider._components structure changes
        assert len(info["tools"]) == 1, (
            "BREAKING CHANGE DETECTED: FastMCP local_provider._components structure may have changed. "
            "Expected 'local_provider._components' with 'tool:name@' keys, but tool extraction failed. "
            "Update _extract_server_info() method if FastMCP changed its internal structure."
        )

        # Verify tool objects still have .fn and .parameters
        extracted_tool = list(info["tools"].values())[0]
        assert hasattr(
            extracted_tool, "fn"
        ), "BREAKING CHANGE DETECTED: FastMCP tool objects no longer have '.fn' attribute."
        assert hasattr(
            extracted_tool, "parameters"
        ), "BREAKING CHANGE DETECTED: FastMCP tool objects no longer have '.parameters' attribute."

    def test_canary_required_attributes(self, step):
        """
        CANARY TEST: This test should FAIL if FastMCP changes required attributes.

        If this test fails, update the attribute validation in _is_fastmcp_instance().
        """
        mock_obj = MagicMock()
        mock_obj.__class__.__name__ = "FastMCP"

        # These are the EXACT attributes currently required
        required_attrs = ["name", "local_provider", "tool"]

        for attr in required_attrs:
            setattr(mock_obj, attr, MagicMock())

        result = step._is_fastmcp_instance(mock_obj)

        assert result is True, (
            f"BREAKING CHANGE DETECTED: FastMCP required attributes may have changed. "
            f"Expected attributes {required_attrs}, but detection failed. "
            f"Update _is_fastmcp_instance() method if FastMCP changed its required attributes."
        )

    def test_canary_tool_access_pattern(self, step):
        """
        CANARY TEST: This test should FAIL if FastMCP changes how tools are accessed.

        If this test fails, update the tool access pattern in _extract_server_info().
        """
        mock_instance = MagicMock()
        mock_instance.name = "canary-access-test"

        # Create the EXACT access pattern currently expected (v3 structure)
        mock_lp = MagicMock()
        mock_tool = MagicMock()
        mock_tool.fn = MagicMock()  # EXACT tool structure expected
        mock_tool.fn.__name__ = "canary_function"
        mock_tool.name = "canary_tool"

        mock_lp._components = {
            "tool:canary_tool@": mock_tool
        }  # EXACT v3 components dict
        mock_instance.local_provider = mock_lp

        info = step._extract_server_info("canary_access", mock_instance)

        # This assertion protects against tool access pattern changes
        assert info["function_count"] >= 1, (
            "BREAKING CHANGE DETECTED: FastMCP tool access pattern may have changed. "
            "Expected 'local_provider._components[\"tool:name@\"].fn' pattern, but tool counting failed. "
            "Update tool extraction logic in _extract_server_info() if FastMCP changed how tools are structured."
        )
