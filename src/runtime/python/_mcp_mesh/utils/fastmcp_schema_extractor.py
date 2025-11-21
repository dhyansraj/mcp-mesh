"""
FastMCP Schema Extractor

Extracts inputSchema from FastMCP tool objects for LLM integration.
This enables the registry to store tool schemas for tool discovery.

Part of Phase 2: Schema Collection & Propagation
Part of Phase 2.5: Schema Filtering - removes dependency injection parameters
Part of Phase 0: Enhanced Schema Extraction - MeshContextModel support
"""

import inspect
import logging
from typing import Any, Dict, Optional, get_args, get_origin, get_type_hints

logger = logging.getLogger(__name__)


class FastMCPSchemaExtractor:
    """
    Extracts inputSchema from FastMCP tools.

    FastMCP automatically generates JSON schemas from Python type hints.
    This class extracts those schemas so they can be sent to the registry
    for LLM tool discovery.

    Phase 2.5: Filters out McpMeshAgent parameters from schemas since
    they are dependency injection parameters and should not be visible to LLMs.

    Phase 0: Enhances schemas with MeshContextModel Field descriptions for
    better LLM chain composition.
    """

    @staticmethod
    def is_mesh_context_model(type_hint: Any) -> bool:
        """
        Check if a type hint is MeshContextModel or a subclass.

        Handles:
        - Direct MeshContextModel subclass
        - Optional[MeshContextModel] (Union with None)
        - Forward references

        Args:
            type_hint: Type annotation to check

        Returns:
            True if type is MeshContextModel or subclass

        Example:
            class ChatContext(MeshContextModel):
                ...

            is_mesh_context_model(ChatContext) # True
            is_mesh_context_model(Optional[ChatContext]) # True
            is_mesh_context_model(str) # False
        """
        try:
            from mesh.types import MeshContextModel

            # Handle None
            if type_hint is None:
                return False

            # Handle Union types (like Optional[MeshContextModel])
            origin = get_origin(type_hint)
            if origin is not None:
                # For Union types, check all args
                args = get_args(type_hint)
                for arg in args:
                    if arg is not type(
                        None
                    ) and FastMCPSchemaExtractor.is_mesh_context_model(arg):
                        return True
                return False

            # Direct type check
            if inspect.isclass(type_hint):
                return issubclass(type_hint, MeshContextModel)

        except (ImportError, TypeError):
            # MeshContextModel not available or type checking failed
            pass

        return False

    @staticmethod
    def extract_context_schema(model_class: type) -> dict[str, Any]:
        """
        Extract enhanced schema from MeshContextModel with Field descriptions.

        Uses Pydantic's model_json_schema() to get complete schema including:
        - Field descriptions from Field(description=...)
        - Default values
        - Type information
        - Nested models

        Args:
            model_class: MeshContextModel subclass

        Returns:
            Enhanced JSON Schema dict with descriptions

        Example:
            class AnalysisContext(MeshContextModel):
                domain: str = Field(description="Analysis domain")
                user_level: str = Field(default="beginner")

            schema = extract_context_schema(AnalysisContext)
            # Returns:
            # {
            #     "type": "object",
            #     "properties": {
            #         "domain": {"type": "string", "description": "Analysis domain"},
            #         "user_level": {"type": "string", "default": "beginner"}
            #     },
            #     "required": ["domain"]
            # }
        """
        try:
            # Get Pydantic's JSON schema which includes all Field metadata
            schema = model_class.model_json_schema()

            # Add marker that this is a context for prompt template
            if "description" not in schema:
                schema["description"] = "Context for prompt template"
            else:
                # Append to existing description
                schema["description"] = (
                    f"{schema['description']} (Context for prompt template)"
                )

            logger.debug(
                f"Extracted enhanced schema for {model_class.__name__}: "
                f"{list(schema.get('properties', {}).keys())}"
            )

            return schema

        except Exception as e:
            logger.warning(f"Failed to extract schema from {model_class.__name__}: {e}")
            return {"type": "object"}

    @staticmethod
    def enhance_schema_with_context_models(
        schema: dict[str, Any], function: Any
    ) -> dict[str, Any]:
        """
        Enhance schema by detecting MeshContextModel parameters and extracting
        their Field descriptions.

        Phase 0: For each parameter that is a MeshContextModel subclass, replace
        the basic schema with an enhanced schema that includes Field descriptions.
        This helps calling LLM agents construct context objects correctly.

        Args:
            schema: The inputSchema dict to enhance
            function: The function whose parameters to analyze

        Returns:
            Enhanced schema with MeshContextModel Field descriptions

        Example:
            Before:
            {
                "properties": {
                    "ctx": {"type": "object"}  # Basic
                }
            }

            After:
            {
                "properties": {
                    "ctx": {
                        "type": "object",
                        "description": "Context for prompt template",
                        "properties": {
                            "domain": {
                                "type": "string",
                                "description": "Analysis domain: infrastructure, security"
                            }
                        }
                    }
                }
            }
        """
        if not schema or not isinstance(schema, dict):
            return schema

        try:
            # Get type hints from function
            type_hints = get_type_hints(function)
        except Exception as e:
            func_name = getattr(function, "__name__", "<unknown>")
            logger.debug(f"Could not get type hints for {func_name}: {e}")
            return schema

        # Create a copy to avoid modifying original
        enhanced_schema = schema.copy()
        if "properties" not in enhanced_schema:
            return enhanced_schema

        enhanced_props = enhanced_schema["properties"].copy()

        # Check each parameter
        for param_name, param_schema in schema.get("properties", {}).items():
            type_hint = type_hints.get(param_name)

            if type_hint and FastMCPSchemaExtractor.is_mesh_context_model(type_hint):
                # Found MeshContextModel parameter!
                # Extract the actual model class (handle Optional)
                model_class = type_hint
                origin = get_origin(type_hint)
                if origin is not None:
                    args = get_args(type_hint)
                    for arg in args:
                        if arg is not type(None):
                            model_class = arg
                            break

                # Extract enhanced schema with Field descriptions
                context_schema = FastMCPSchemaExtractor.extract_context_schema(
                    model_class
                )

                # Replace basic schema with enhanced schema
                enhanced_props[param_name] = context_schema

                logger.debug(
                    f"Enhanced {param_name} parameter with MeshContextModel schema: "
                    f"{list(context_schema.get('properties', {}).keys())}"
                )

        enhanced_schema["properties"] = enhanced_props
        return enhanced_schema

    @staticmethod
    def filter_dependency_parameters(
        schema: dict[str, Any], function: Any
    ) -> dict[str, Any]:
        """
        Filter out McpMeshAgent dependency injection parameters from schema.

        Phase 2.5: Remove dependency injection parameters from LLM-facing schemas.
        These parameters are injected at runtime by MCP Mesh and should not be
        visible to LLMs or included in tool discovery.

        Args:
            schema: The inputSchema dict to filter
            function: The function whose parameters to analyze

        Returns:
            Filtered schema with dependency parameters removed

        Example:
            Input schema:
            {
                "properties": {
                    "name": {"type": "string"},
                    "date_service": {"anyOf": [{}, {"type": "null"}], "default": null}
                },
                "required": ["name"]
            }

            Output schema (date_service removed):
            {
                "properties": {
                    "name": {"type": "string"}
                },
                "required": ["name"]
            }
        """
        if not schema or not isinstance(schema, dict):
            return schema

        # Get McpMeshAgent parameter names from signature analysis
        from _mcp_mesh.engine.signature_analyzer import get_mesh_agent_parameter_names

        mesh_param_names = get_mesh_agent_parameter_names(function)

        if not mesh_param_names:
            # No dependency parameters to filter
            return schema

        # Create a copy to avoid modifying original
        filtered_schema = schema.copy()

        # Filter properties
        if "properties" in filtered_schema:
            original_props = filtered_schema["properties"]
            filtered_props = {
                param_name: param_schema
                for param_name, param_schema in original_props.items()
                if param_name not in mesh_param_names
            }
            filtered_schema["properties"] = filtered_props

            logger.debug(
                f"🔧 Filtered {len(original_props) - len(filtered_props)} dependency parameters "
                f"from schema: {mesh_param_names}"
            )

        # Filter required array
        if "required" in filtered_schema:
            original_required = filtered_schema["required"]
            filtered_required = [
                param_name
                for param_name in original_required
                if param_name not in mesh_param_names
            ]
            filtered_schema["required"] = filtered_required

        return filtered_schema

    @staticmethod
    def extract_input_schema(function: Any) -> Optional[dict[str, Any]]:
        """
        Extract inputSchema from a function that may have a FastMCP tool attached.

        Args:
            function: The function object (possibly decorated with @app.tool())

        Returns:
            inputSchema dict if FastMCP tool found, None otherwise

        The inputSchema format follows JSON Schema specification:
        {
            "type": "object",
            "properties": {
                "param_name": {"type": "string", "description": "..."},
                ...
            },
            "required": ["param1", "param2"]
        }
        """
        # Check if function has FastMCP tool reference
        if not hasattr(function, "_fastmcp_tool"):
            logger.debug(
                f"Function {getattr(function, '__name__', '<unknown>')} has no FastMCP tool"
            )
            return None

        fastmcp_tool = function._fastmcp_tool

        # Extract inputSchema from FastMCP tool
        # FastMCP uses 'parameters' attribute, not 'inputSchema'
        if hasattr(fastmcp_tool, "parameters"):
            schema = fastmcp_tool.parameters
            logger.debug(
                f"Extracted schema from {getattr(function, '__name__', '<unknown>')}: "
                f"{list(schema.get('properties', {}).keys()) if isinstance(schema, dict) else 'invalid'}"
            )
            # Phase 2.5: Filter out dependency injection parameters
            filtered_schema = FastMCPSchemaExtractor.filter_dependency_parameters(
                schema, function
            )

            # Phase 0: Enhance schema with MeshContextModel Field descriptions
            enhanced_schema = FastMCPSchemaExtractor.enhance_schema_with_context_models(
                filtered_schema, function
            )

            return enhanced_schema

        logger.debug(
            f"FastMCP tool for {getattr(function, '__name__', '<unknown>')} "
            f"has no parameters attribute"
        )
        return None

    @staticmethod
    def extract_from_fastmcp_servers(
        function: Any, fastmcp_servers: Optional[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """
        Extract inputSchema by looking up function in FastMCP server tool managers.

        This is the primary method for extracting schemas when using FastMCP.
        It searches all discovered FastMCP servers for a tool whose function
        matches the given function, then extracts its inputSchema.

        Args:
            function: The function to find schema for
            fastmcp_servers: Dict from fastmcp-server-discovery step context
                            (maps server_name -> server_info dict)

        Returns:
            inputSchema dict if found, None otherwise
        """
        if not fastmcp_servers:
            return None

        func_id = id(function)
        func_name = getattr(function, "__name__", "<unknown>")

        # Search all FastMCP servers for this function
        for server_name, server_info in fastmcp_servers.items():
            tools_dict = server_info.get("tools", {})

            # Look through all tools in this server
            for tool_name, tool_obj in tools_dict.items():
                # Match by function identity
                tool_fn = getattr(tool_obj, "fn", None)
                if tool_fn is not None and id(tool_fn) == func_id:
                    # Found matching tool! Extract schema
                    # FastMCP stores schema in 'parameters' attribute (not 'inputSchema')
                    if hasattr(tool_obj, "parameters"):
                        schema = tool_obj.parameters
                        logger.debug(
                            f"✅ Matched function {func_name} to FastMCP tool '{tool_name}' "
                            f"with schema: {list(schema.get('properties', {}).keys()) if isinstance(schema, dict) else 'invalid'}"
                        )
                        # Phase 2.5: Filter out dependency injection parameters
                        filtered_schema = (
                            FastMCPSchemaExtractor.filter_dependency_parameters(
                                schema, function
                            )
                        )

                        # Phase 0: Enhance schema with MeshContextModel Field descriptions
                        enhanced_schema = (
                            FastMCPSchemaExtractor.enhance_schema_with_context_models(
                                filtered_schema, function
                            )
                        )

                        return enhanced_schema
                    else:
                        logger.debug(
                            f"⚠️ Matched function {func_name} to FastMCP tool '{tool_name}' "
                            f"but no parameters attribute found"
                        )
                        return None

        logger.debug(
            f"Function {func_name} not found in any FastMCP server tool managers"
        )
        return None

    @staticmethod
    def extract_all_schemas_from_tools(
        mesh_tools: dict[str, Any], fastmcp_servers: Optional[dict[str, Any]] = None
    ) -> dict[str, Optional[dict[str, Any]]]:
        """
        Extract inputSchemas from all tools in a mesh_tools dict.

        Args:
            mesh_tools: Dict of function_name -> DecoratedFunction
            fastmcp_servers: Optional dict of FastMCP server info from discovery step

        Returns:
            Dict mapping function_name -> inputSchema (or None)
        """
        schemas = {}

        for func_name, decorated_func in mesh_tools.items():
            function = decorated_func.function

            # First try the FastMCP server lookup (primary method)
            schema = FastMCPSchemaExtractor.extract_from_fastmcp_servers(
                function, fastmcp_servers
            )

            # Fallback to _fastmcp_tool attribute (for backward compatibility with tests)
            if schema is None:
                schema = FastMCPSchemaExtractor.extract_input_schema(function)

            schemas[func_name] = schema

        logger.info(
            f"Extracted schemas for {len(mesh_tools)} tools: "
            f"{sum(1 for s in schemas.values() if s is not None)} with schemas, "
            f"{sum(1 for s in schemas.values() if s is None)} without"
        )

        return schemas
