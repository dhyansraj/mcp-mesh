"""
MeshLlmAgent dependency injection system.

Handles injection of MeshLlmAgent proxies into function parameters.
Similar to DependencyInjector but specialized for LLM agent injection.
"""

import inspect
import logging
from collections.abc import Callable
from typing import Any

from .base_injector import BaseInjector
from .decorator_registry import DecoratorRegistry
from .llm_config import LLMConfig
from .mesh_llm_agent import MeshLlmAgent
from .unified_mcp_proxy import UnifiedMCPProxy

logger = logging.getLogger(__name__)


def extract_vendor_from_model(model: str) -> str | None:
    """
    Extract vendor name from LiteLLM model string.

    LiteLLM uses vendor/model format (e.g., "anthropic/claude-sonnet-4-5").
    This extracts the vendor for provider handler selection.

    Args:
        model: LiteLLM model string

    Returns:
        Vendor name (e.g., "anthropic", "openai") or None if not extractable

    Examples:
        "anthropic/claude-sonnet-4-5" -> "anthropic"
        "openai/gpt-4o" -> "openai"
        "gpt-4" -> None (no vendor prefix)
    """
    if not model:
        return None

    if "/" in model:
        vendor = model.split("/")[0].lower().strip()
        logger.debug(f"🔍 Extracted vendor '{vendor}' from model '{model}'")
        return vendor

    return None


class MeshLlmAgentInjector(BaseInjector):
    """
    Manages dynamic injection of MeshLlmAgent proxies.

    This class:
    1. Consumes llm_tools from registry response
    2. Creates UnifiedMCPProxy instances for each tool
    3. Creates MeshLlmAgent instances with config + proxies + output_type
    4. Injects MeshLlmAgent into function parameters
    5. Handles topology updates when tools join/leave
    """

    def __init__(self):
        """Initialize the LLM agent injector."""
        super().__init__()
        self._llm_agents: dict[str, dict[str, Any]] = {}

    def initialize_direct_llm_agents(self) -> None:
        """
        Initialize LLM agents that use direct LiteLLM (no mesh delegation).

        This handles the case where:
        - provider is a string (e.g., "claude") - direct LiteLLM call
        - filter is None or empty - no mesh tools needed

        These agents don't need to wait for registry response since all
        information is available at decorator time.
        """
        llm_agents = DecoratorRegistry.get_mesh_llm_agents()

        for function_id, llm_metadata in llm_agents.items():
            config = llm_metadata.config
            provider = config.get("provider")
            filter_config = config.get("filter")

            # Check if this is a direct LiteLLM agent (provider is string, not dict)
            is_direct_llm = isinstance(provider, str)

            # Check if no tools needed (filter is None or empty)
            has_no_filter = filter_config is None or (
                isinstance(filter_config, list) and len(filter_config) == 0
            )

            if is_direct_llm and has_no_filter:
                # Skip if already initialized
                if function_id in self._llm_agents:
                    continue

                logger.info(
                    f"🔧 Initializing direct LiteLLM agent for '{function_id}' "
                    f"(provider={provider}, no filter)"
                )

                # Initialize empty tools data for direct LiteLLM
                self._llm_agents[function_id] = {
                    "config": config,
                    "output_type": llm_metadata.output_type,
                    "param_name": llm_metadata.param_name,
                    "tools_metadata": [],  # No tools for direct LiteLLM
                    "tools_proxies": {},  # No tool proxies needed
                    "function": llm_metadata.function,
                    "provider_proxy": None,  # No mesh delegation
                }

                # Get the wrapper and update it with LLM agent
                wrapper = llm_metadata.function
                if wrapper and hasattr(wrapper, "_mesh_update_llm_agent"):
                    llm_agent = self._create_llm_agent(function_id)
                    wrapper._mesh_update_llm_agent(llm_agent)
                    logger.info(
                        f"🔄 Updated wrapper with MeshLlmAgent for '{function_id}' (direct LiteLLM mode)"
                    )

                    # Set factory for per-call context agent creation (template support)
                    if config.get("is_template", False):
                        def create_context_agent(
                            context_value: Any, _func_id: str = function_id
                        ) -> MeshLlmAgent:
                            """Factory to create MeshLlmAgent with context for template rendering."""
                            return self._create_llm_agent(_func_id, context_value=context_value)

                        wrapper._mesh_create_context_agent = create_context_agent
                        logger.info(
                            f"🎯 Set context agent factory for template-based function '{function_id}' (direct LiteLLM mode)"
                        )

    def _build_function_name_to_id_mapping(self) -> dict[str, str]:
        """
        Build mapping from function_name to function_id.

        Registry returns llm_tools keyed by function_name (e.g., "chat"),
        but DecoratorRegistry stores LLM agents keyed by function_id (e.g., "chat_ac4ed56b").

        Returns:
            Dict mapping function_name -> function_id
        """
        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        return {
            metadata.function.__name__: function_id
            for function_id, metadata in llm_agents.items()
        }

    def process_llm_tools(self, llm_tools: dict[str, list[dict[str, Any]]]) -> None:
        """
        Process llm_tools from registry response.

        Creates UnifiedMCPProxy instances and MeshLlmAgent instances
        for each function_id.

        Args:
            llm_tools: Dict mapping function_name -> list of tool metadata
                      Format: {"function_name": [{"function_name": "...", "endpoint": {...}, ...}]}
                      Note: Registry uses function_name as key, but we need to map to function_id
        """
        logger.info(f"🔧 Processing llm_tools for {len(llm_tools)} functions")

        # Build mapping from function_name to function_id
        function_name_to_id = self._build_function_name_to_id_mapping()

        for function_name, tools in llm_tools.items():
            try:
                # Map function_name to function_id
                if function_name not in function_name_to_id:
                    logger.warning(
                        f"⚠️ Function name '{function_name}' not found in DecoratorRegistry, skipping"
                    )
                    continue

                function_id = function_name_to_id[function_name]
                self._process_function_tools(function_id, tools)
            except Exception as e:
                logger.error(
                    f"❌ Error processing llm_tools for {function_name}: {e}",
                    exc_info=True,
                )

    def process_llm_providers(self, llm_providers: dict[str, dict[str, Any]]) -> None:
        """
        Process llm_providers from registry response (v0.6.1 mesh delegation).

        Creates UnifiedMCPProxy instances for each resolved LLM provider
        and updates existing MeshLlmAgent instances.

        Args:
            llm_providers: Dict mapping function_name -> ResolvedLLMProvider
                         Format: {"function_name": {"agent_id": "...", "endpoint": "...", ...}}
        """
        logger.info(f"🔌 Processing llm_providers for {len(llm_providers)} functions")

        # Build mapping from function_name to function_id
        function_name_to_id = self._build_function_name_to_id_mapping()

        for function_name, provider_data in llm_providers.items():
            try:
                # Map function_name to function_id
                if function_name not in function_name_to_id:
                    logger.warning(
                        f"⚠️ Function name '{function_name}' not found in DecoratorRegistry for provider, skipping"
                    )
                    continue

                function_id = function_name_to_id[function_name]
                self._process_function_provider(function_id, provider_data)
            except Exception as e:
                logger.error(
                    f"❌ Error processing llm_provider for {function_name}: {e}",
                    exc_info=True,
                )

    def _process_function_provider(
        self, function_id: str, provider_data: dict[str, Any]
    ) -> None:
        """
        Process LLM provider for a single function.

        Args:
            function_id: Unique function ID from @mesh.llm decorator
            provider_data: ResolvedLLMProvider data from registry
        """
        # Create UnifiedMCPProxy for the provider
        provider_proxy = self._create_provider_proxy(provider_data)

        # Update only provider-related fields, preserving tool data if already set.
        # This avoids race conditions where provider and tools updates can arrive in any order.
        if function_id not in self._llm_agents:
            self._llm_agents[function_id] = {}

        # Phase 2: Extract vendor from provider_data for handler selection
        vendor = provider_data.get("vendor", "unknown")

        self._llm_agents[function_id]["provider_proxy"] = provider_proxy
        self._llm_agents[function_id]["vendor"] = vendor

        logger.info(
            f"✅ Set provider proxy for '{function_id}': {provider_proxy.function_name} at {provider_proxy.endpoint} (vendor={vendor})"
        )

        # Re-create and update MeshLlmAgent with new provider
        # Get the function wrapper and metadata from DecoratorRegistry
        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        wrapper = None
        llm_metadata = None
        for agent_func_id, metadata in llm_agents.items():
            if metadata.function_id == function_id:
                wrapper = metadata.function
                llm_metadata = metadata
                break

        # Check if tools are required (filter is specified)
        has_filter = False
        if llm_metadata and llm_metadata.config:
            filter_config = llm_metadata.config.get("filter")
            has_filter = filter_config is not None and len(filter_config) > 0

        # If no filter specified, initialize empty tools data so we can create LLM agent without tools
        # This supports simple LLM calls (text generation) that don't need tool calling
        if not has_filter and "tools_metadata" not in self._llm_agents[function_id]:
            self._llm_agents[function_id].update(
                {
                    "config": llm_metadata.config if llm_metadata else {},
                    "output_type": llm_metadata.output_type if llm_metadata else None,
                    "param_name": llm_metadata.param_name if llm_metadata else "llm",
                    "tools_metadata": [],  # No tools for simple LLM calls
                    "tools_proxies": {},  # No tool proxies needed
                    "function": llm_metadata.function if llm_metadata else None,
                }
            )
            logger.info(
                f"✅ Initialized empty tools for '{function_id}' (no filter specified - simple LLM mode)"
            )

        # Update wrapper if we have tools data (either from filter matching or initialized empty)
        if (
            wrapper
            and hasattr(wrapper, "_mesh_update_llm_agent")
            and "tools_metadata" in self._llm_agents[function_id]
        ):
            llm_agent = self._create_llm_agent(function_id)
            wrapper._mesh_update_llm_agent(llm_agent)
            logger.info(
                f"🔄 Updated wrapper with MeshLlmAgent for '{function_id}'"
                + (" (with tools)" if has_filter else " (simple LLM mode)")
            )

            # Set factory for per-call context agent creation (template support)
            # This is critical for filter=None cases where _process_function_tools isn't called
            config_dict = llm_metadata.config if llm_metadata else {}
            if config_dict.get("is_template", False):
                # Capture function_id by value using default argument to avoid closure issues
                def create_context_agent(
                    context_value: Any, _func_id: str = function_id
                ) -> MeshLlmAgent:
                    """Factory to create MeshLlmAgent with context for template rendering."""
                    return self._create_llm_agent(_func_id, context_value=context_value)

                wrapper._mesh_create_context_agent = create_context_agent
                logger.info(
                    f"🎯 Set context agent factory for template-based function '{function_id}' (simple LLM mode)"
                )
        elif wrapper and hasattr(wrapper, "_mesh_update_llm_agent") and has_filter:
            logger.debug(
                f"⏳ Provider set for '{function_id}', waiting for tools before updating wrapper"
            )

    def _create_provider_proxy(self, provider_data: dict[str, Any]) -> UnifiedMCPProxy:
        """
        Create UnifiedMCPProxy for an LLM provider.

        Args:
            provider_data: ResolvedLLMProvider data from registry

        Returns:
            UnifiedMCPProxy instance

        Raises:
            ValueError: If endpoint is missing or invalid
        """
        function_name = provider_data.get("name")
        if not function_name:
            raise ValueError(f"Provider missing required 'name' field: {provider_data}")

        endpoint = provider_data.get("endpoint")
        if not endpoint:
            raise ValueError(f"Provider {function_name} missing endpoint")

        if not isinstance(endpoint, str):
            raise ValueError(
                f"Provider {function_name} has invalid endpoint (expected string): {endpoint}"
            )

        # Create proxy with endpoint URL
        proxy = UnifiedMCPProxy(
            endpoint=endpoint,
            function_name=function_name,
            kwargs_config={
                "capability": provider_data.get("capability", "llm"),
                "agent_id": provider_data.get("agent_id"),
            },
        )

        logger.debug(f"🔧 Created provider proxy for {function_name} at {endpoint}")

        return proxy

    def _process_function_tools(
        self, function_id: str, tools: list[dict[str, Any]]
    ) -> None:
        """
        Process tools for a single function.

        Args:
            function_id: Unique function ID from @mesh.llm decorator
            tools: List of tool metadata from registry
        """
        # Get LLM agent metadata from DecoratorRegistry
        llm_agents = DecoratorRegistry.get_mesh_llm_agents()

        if function_id not in llm_agents:
            logger.warning(
                f"⚠️ Function '{function_id}' not found in DecoratorRegistry, skipping"
            )
            return

        llm_metadata = llm_agents[function_id]

        # Create UnifiedMCPProxy instances for each tool and build proxy map
        tool_proxies_map = {}  # Map function_name -> proxy
        for tool in tools:
            try:
                proxy = self._create_tool_proxy(tool)
                # OpenAPI spec uses "name" (camelCase) - enforce strict contract
                function_name = tool.get("name")
                if function_name:
                    tool_proxies_map[function_name] = proxy
                else:
                    logger.error(
                        f"❌ Tool missing 'name' field (OpenAPI contract): {tool}"
                    )
            except Exception as e:
                # Get tool name for error message
                tool_name = tool.get("name", "unknown")
                logger.error(f"❌ Error creating proxy for tool {tool_name}: {e}")
                # Continue processing other tools

        # Update only tool-related fields, preserving provider_proxy if already set.
        # Provider proxy is managed separately by process_llm_providers().
        # This avoids race conditions where tools update wipes out provider resolution.
        if function_id not in self._llm_agents:
            self._llm_agents[function_id] = {}

        self._llm_agents[function_id].update(
            {
                "config": llm_metadata.config,
                "output_type": llm_metadata.output_type,
                "param_name": llm_metadata.param_name,
                "tools_metadata": tools,  # Original metadata for schema building
                "tools_proxies": tool_proxies_map,  # Proxies for execution
                "function": llm_metadata.function,
                # Note: provider_proxy is NOT set here - managed by _process_function_provider
            }
        )

        logger.info(
            f"✅ Processed {len(tool_proxies_map)} tools for LLM function '{function_id}'"
        )

        # Update wrapper with MeshLlmAgent (two-phase pattern - Phase 2)
        # Option A: Decorator stores function in DecoratorRegistry (not _function_registry)
        # Get the function from DecoratorRegistry by matching function_id
        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        wrapper = None
        for agent_func_id, metadata in llm_agents.items():
            if metadata.function_id == function_id:
                wrapper = metadata.function
                break

        if wrapper and hasattr(wrapper, "_mesh_update_llm_agent"):
            llm_agent = self._create_llm_agent(function_id)
            wrapper._mesh_update_llm_agent(llm_agent)
            logger.info(f"🔄 Updated wrapper with MeshLlmAgent for '{function_id}'")

            # Set factory for per-call context agent creation (template support)
            # This allows the decorator's wrapper to create new agents with context per-call
            config_dict = llm_metadata.config
            if config_dict.get("is_template", False):
                # Capture function_id by value using default argument to avoid closure issues
                def create_context_agent(
                    context_value: Any, _func_id: str = function_id
                ) -> MeshLlmAgent:
                    """Factory to create MeshLlmAgent with context for template rendering."""
                    return self._create_llm_agent(_func_id, context_value=context_value)

                wrapper._mesh_create_context_agent = create_context_agent
                logger.info(
                    f"🎯 Set context agent factory for template-based function '{function_id}'"
                )
        elif wrapper:
            logger.warning(
                f"⚠️ Wrapper for '{function_id}' found but has no _mesh_update_llm_agent method"
            )
        else:
            logger.warning(
                f"⚠️ No wrapper found for '{function_id}' - MeshLlmAgent not injected (decorator should have created it)"
            )

    def _create_tool_proxy(self, tool: dict[str, Any]) -> UnifiedMCPProxy:
        """
        Create UnifiedMCPProxy for a tool.

        Args:
            tool: Tool metadata from registry (must match OpenAPI spec field names)

        Returns:
            UnifiedMCPProxy instance

        Raises:
            ValueError: If endpoint is missing or invalid
        """
        # OpenAPI spec uses "name" (camelCase) - enforce strict contract
        function_name = tool.get("name")
        if not function_name:
            raise ValueError(
                f"Tool missing required 'name' field (OpenAPI contract): {tool}"
            )

        endpoint = tool.get("endpoint")
        if not endpoint:
            raise ValueError(f"Tool {function_name} missing endpoint")

        # Registry returns endpoint as a string URL (e.g., "http://localhost:9091")
        # Use it directly instead of parsing host/port
        if not isinstance(endpoint, str):
            raise ValueError(
                f"Tool {function_name} has invalid endpoint (expected string): {endpoint}"
            )

        # Create proxy with endpoint URL
        proxy = UnifiedMCPProxy(
            endpoint=endpoint,
            function_name=function_name,
            kwargs_config={
                "capability": tool.get("capability"),
            },
        )

        logger.debug(f"🔧 Created proxy for {function_name} at {endpoint}")

        return proxy

    def create_injection_wrapper(self, func: Callable, function_id: str) -> Callable:
        """
        Create wrapper that injects MeshLlmAgent into function parameters.

        Like McpMeshTool injection, this creates a wrapper at decorator time with llm_agent=None,
        which gets updated during heartbeat when tools arrive from registry.

        Args:
            func: Original function to wrap
            function_id: Unique function ID

        Returns:
            Wrapped function with MeshLlmAgent injection
        """
        # Get LLM metadata from DecoratorRegistry (registered at decorator time)
        llm_agents = DecoratorRegistry.get_mesh_llm_agents()

        if function_id not in llm_agents:
            logger.warning(
                f"⚠️ Function '{function_id}' not found in DecoratorRegistry, creating wrapper anyway"
            )
            # Get param_name from stored data if available, otherwise raise
            if function_id in self._llm_agents:
                param_name = self._llm_agents[function_id]["param_name"]
            else:
                raise ValueError(
                    f"Function '{function_id}' not found in LLM agent registry"
                )
        else:
            llm_metadata = llm_agents[function_id]
            param_name = llm_metadata.param_name

            # Validate parameter exists
            sig = inspect.signature(func)
            if param_name not in sig.parameters:
                raise ValueError(
                    f"Function '{func.__name__}' missing MeshLlmAgent parameter '{param_name}'"
                )

        # Initialize with None (will be updated during heartbeat)
        llm_agent = None

        # Create injection logic closure
        def inject_llm_agent(func: Callable, args: tuple, kwargs: dict) -> tuple:
            """Inject LLM agent into kwargs if not provided."""
            if param_name not in kwargs or kwargs.get(param_name) is None:
                # Get config from runtime data or fallback to decorator registry.
                # Runtime data (self._llm_agents) is populated during heartbeat and has
                # tools/provider info. Decorator registry is populated at decorator time
                # and always has config/context_param. For self-dependency calls that
                # happen before heartbeat, we need the decorator registry fallback.
                agent_data = None
                config_dict = None

                # Try runtime data first (has tools, provider from heartbeat)
                if function_id in self._llm_agents:
                    agent_data = self._llm_agents[function_id]
                    config_dict = agent_data.get("config")

                # Fallback to decorator registry (always available, has context_param)
                # This is critical for self-dependency calls that happen before heartbeat
                if config_dict is None:
                    llm_agents_registry = DecoratorRegistry.get_mesh_llm_agents()
                    if function_id in llm_agents_registry:
                        llm_metadata = llm_agents_registry[function_id]
                        config_dict = llm_metadata.config
                        logger.debug(
                            f"🔄 Using DecoratorRegistry fallback for '{function_id}' config (self-dependency before heartbeat)"
                        )

                # Check if templates are enabled
                is_template = config_dict.get("is_template", False) if config_dict else False

                if is_template and config_dict:
                    # Templates enabled - create per-call agent with context
                    # Import signature analyzer for context detection
                    from .signature_analyzer import get_context_parameter_name

                    # Detect context parameter
                    context_param_name = config_dict.get("context_param")
                    context_info = get_context_parameter_name(
                        func, explicit_name=context_param_name
                    )

                    # Extract context value from call
                    context_value = None
                    if context_info is not None:
                        ctx_name, ctx_index = context_info

                        # Try kwargs first
                        if ctx_name in kwargs:
                            context_value = kwargs[ctx_name]
                        # Then try positional args
                        elif ctx_index < len(args):
                            context_value = args[ctx_index]

                    # Create agent with context for this call
                    # Note: _create_llm_agent requires function_id in self._llm_agents
                    # If not available yet, use cached agent with context_value set directly
                    if function_id in self._llm_agents:
                        current_agent = self._create_llm_agent(
                            function_id, context_value=context_value
                        )
                        logger.debug(
                            f"🤖 Created MeshLlmAgent with context for {func.__name__}.{param_name}"
                        )
                    else:
                        # Runtime data not yet available - use cached agent but log warning
                        # The cached agent may have been created without context
                        current_agent = wrapper._mesh_llm_agent
                        if current_agent is not None:
                            # Update context on the cached agent if possible
                            if hasattr(current_agent, "_context_value"):
                                current_agent._context_value = context_value
                                logger.debug(
                                    f"🤖 Updated context on cached MeshLlmAgent for {func.__name__}.{param_name}"
                                )
                            else:
                                logger.debug(
                                    f"🤖 Injected cached MeshLlmAgent into {func.__name__}.{param_name} (context may not be applied)"
                                )
                        else:
                            logger.warning(
                                f"⚠️ MeshLlmAgent for {func.__name__}.{param_name} is None (tools not yet received from registry)"
                            )
                elif config_dict:
                    # No template - use cached agent (existing behavior)
                    current_agent = wrapper._mesh_llm_agent
                    if current_agent is not None:
                        logger.debug(
                            f"🤖 Injected MeshLlmAgent into {func.__name__}.{param_name}"
                        )
                    else:
                        logger.warning(
                            f"⚠️ MeshLlmAgent for {func.__name__}.{param_name} is None (tools not yet received from registry)"
                        )
                else:
                    # No config found anywhere - use cached (backward compatibility)
                    current_agent = wrapper._mesh_llm_agent
                    if current_agent is None:
                        logger.warning(
                            f"⚠️ MeshLlmAgent for {func.__name__}.{param_name} is None (no config found)"
                        )

                kwargs[param_name] = current_agent
            return args, kwargs

        # Create update method closure
        def update_llm_agent(agent: MeshLlmAgent | None) -> None:
            wrapper._mesh_llm_agent = agent
            logger.info(
                f"🔄 Updated MeshLlmAgent for {func.__name__} (function_id={function_id})"
            )

        # Prepare metadata
        metadata = {
            "_mesh_llm_agent": llm_agent,
            "_mesh_param_name": param_name,
            "_mesh_update_llm_agent": update_llm_agent,
        }

        # Use base class to create wrapper (handles async/sync automatically)
        wrapper = self.create_wrapper_with_injection(
            func, function_id, inject_llm_agent, metadata, register=True
        )

        logger.debug(
            f"✅ Created LLM injection wrapper for {func.__name__} (agent=None, will be updated during heartbeat)"
        )

        return wrapper

    def _create_llm_agent(
        self, function_id: str, context_value: Any = None
    ) -> MeshLlmAgent:
        """
        Create MeshLlmAgent instance for a function.

        Args:
            function_id: Unique function ID
            context_value: Optional context for template rendering (Phase 4)

        Returns:
            MeshLlmAgent instance configured with tools and config
        """
        llm_agent_data = self._llm_agents[function_id]
        config_dict = llm_agent_data["config"]

        # Create LLMConfig from dict
        llm_config = LLMConfig(
            provider=config_dict.get("provider", "claude"),
            model=config_dict.get("model", "claude-3-5-sonnet-20241022"),
            api_key=config_dict.get("api_key", ""),  # Will use ENV if empty
            max_iterations=config_dict.get("max_iterations", 10),
            system_prompt=config_dict.get("system_prompt"),
            output_mode=config_dict.get(
                "output_mode"
            ),  # Pass through output_mode from decorator
        )

        # Phase 4: Template support - extract template metadata
        is_template = config_dict.get("is_template", False)
        template_path = config_dict.get("template_path")

        # Extract model params (everything except internal config keys)
        # These are passed through to LiteLLM (e.g., max_tokens, temperature)
        INTERNAL_CONFIG_KEYS = {
            "filter",
            "filter_mode",
            "provider",
            "model",
            "api_key",
            "max_iterations",
            "system_prompt",
            "system_prompt_file",
            "is_template",
            "template_path",
            "context_param",
            "output_mode",
        }
        default_model_params = {
            k: v for k, v in config_dict.items() if k not in INTERNAL_CONFIG_KEYS
        }
        if default_model_params:
            logger.debug(
                f"🔧 Extracted default model params for {function_id}: {list(default_model_params.keys())}"
            )

        # Determine vendor for provider handler selection
        # Priority: 1) From registry (mesh delegation), 2) From model name, 3) None
        vendor = llm_agent_data.get("vendor")
        if not vendor:
            # For direct LiteLLM calls, extract vendor from model name
            # e.g., "anthropic/claude-sonnet-4-5" -> "anthropic"
            model = config_dict.get("model", "")
            vendor = extract_vendor_from_model(model)
            if vendor:
                logger.info(
                    f"🔍 Extracted vendor '{vendor}' from model '{model}' for handler selection"
                )

        # Create MeshLlmAgent with both metadata and proxies
        llm_agent = MeshLlmAgent(
            config=llm_config,
            filtered_tools=llm_agent_data[
                "tools_metadata"
            ],  # Metadata for schema building
            output_type=llm_agent_data["output_type"],
            tool_proxies=llm_agent_data["tools_proxies"],  # Proxies for execution
            template_path=template_path if is_template else None,
            context_value=context_value if is_template else None,
            provider_proxy=llm_agent_data.get(
                "provider_proxy"
            ),  # Provider proxy for mesh delegation
            vendor=vendor,  # Vendor for provider handler selection (from registry or model name)
            default_model_params=default_model_params,  # Decorator-level LLM params
        )

        logger.debug(
            f"🤖 Created MeshLlmAgent for {function_id} with {len(llm_agent_data['tools_metadata'])} tools"
            + (f", template={template_path}" if is_template else "")
            + (
                f", provider_proxy={llm_agent_data.get('provider_proxy').function_name if llm_agent_data.get('provider_proxy') else 'None'}"
                if isinstance(config_dict.get("provider"), dict)
                else ""
            )
            + (
                f", model_params={list(default_model_params.keys())}"
                if default_model_params
                else ""
            )
        )

        return llm_agent

    def update_llm_tools(self, llm_tools: dict[str, list[dict[str, Any]]]) -> None:
        """
        Update LLM tools when topology changes.

        Handles:
        - New tools being added
        - Existing tools being removed
        - Entire functions being removed

        Args:
            llm_tools: Updated llm_tools dict from registry (keyed by function_name)
        """
        logger.info(f"🔄 Updating llm_tools for {len(llm_tools)} functions")

        # Build mapping from function_name to function_id
        function_name_to_id = self._build_function_name_to_id_mapping()

        # Map function_names from registry to function_ids
        current_function_ids = set()
        for function_name in llm_tools.keys():
            if function_name in function_name_to_id:
                current_function_ids.add(function_name_to_id[function_name])

        # Track which functions are still active
        previous_functions = set(self._llm_agents.keys())

        # Remove functions that are no longer in the topology
        removed_functions = previous_functions - current_function_ids
        for function_id in removed_functions:
            logger.info(
                f"🗑️ Removing LLM function {function_id} (no longer in topology)"
            )
            del self._llm_agents[function_id]
            # Also remove from function registry if present
            if function_id in self._function_registry:
                del self._function_registry[function_id]

        # Update or add functions
        for function_name, tools in llm_tools.items():
            try:
                # Map function_name to function_id
                if function_name not in function_name_to_id:
                    logger.warning(
                        f"⚠️ Function name '{function_name}' not found in DecoratorRegistry during update, skipping"
                    )
                    continue

                function_id = function_name_to_id[function_name]

                # Reprocess tools (will update existing or create new)
                self._process_function_tools(function_id, tools)

                # Update existing wrappers if they exist
                if function_id in self._function_registry:
                    wrapper = self._function_registry[function_id]
                    # Recreate LLM agent with updated tools
                    new_llm_agent = self._create_llm_agent(function_id)
                    wrapper._mesh_llm_agent = new_llm_agent
                    logger.debug(
                        f"🔄 Updated MeshLlmAgent for existing wrapper: {function_id}"
                    )

            except Exception as e:
                logger.error(
                    f"❌ Error updating llm_tools for {function_name}: {e}",
                    exc_info=True,
                )

        logger.info(
            f"✅ LLM tools update complete: {len(self._llm_agents)} functions active"
        )

    def get_llm_agent_data(self, function_id: str) -> dict[str, Any] | None:
        """
        Get LLM agent data for a function.

        Args:
            function_id: Unique function ID

        Returns:
            LLM agent data dict or None if not found
        """
        return self._llm_agents.get(function_id)


# Global injector instance
_global_llm_injector: MeshLlmAgentInjector | None = None


def get_global_llm_injector() -> MeshLlmAgentInjector:
    """
    Get or create the global MeshLlmAgentInjector instance.

    Returns:
        Global MeshLlmAgentInjector instance
    """
    global _global_llm_injector
    if _global_llm_injector is None:
        _global_llm_injector = MeshLlmAgentInjector()
    return _global_llm_injector
