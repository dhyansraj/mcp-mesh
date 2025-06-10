"""Method metadata types for MCP Mesh signature extraction and service contracts."""

import inspect
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Union


class ParameterKind(Enum):
    """Parameter kind for method parameters."""

    POSITIONAL_ONLY = "positional_only"
    POSITIONAL_OR_KEYWORD = "positional_or_keyword"
    VAR_POSITIONAL = "var_positional"
    KEYWORD_ONLY = "keyword_only"
    VAR_KEYWORD = "var_keyword"


class MethodType(Enum):
    """Type of method for classification."""

    INSTANCE = "instance"
    CLASS = "class"
    STATIC = "static"
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    ASYNC_METHOD = "async_method"


@dataclass
class ParameterMetadata:
    """Metadata for a method parameter."""

    name: str
    type_hint: type
    kind: ParameterKind
    default: Any = inspect.Parameter.empty
    annotation: Any = inspect.Parameter.empty
    has_default: bool = False
    is_optional: bool = False


@dataclass
class MethodMetadata:
    """
    Comprehensive metadata for method signature extraction and service contracts.

    This class stores complete information about a method's signature,
    including parameters, return types, capabilities, and type hints
    for service discovery and contract enforcement.
    """

    method_name: str
    signature: inspect.Signature
    capabilities: list[str] = field(default_factory=list)
    return_type: type = type(None)
    parameters: dict[str, type] = field(default_factory=dict)
    type_hints: dict[str, type] = field(default_factory=dict)

    # Additional metadata for enhanced service contracts
    parameter_metadata: dict[str, ParameterMetadata] = field(default_factory=dict)
    method_type: MethodType = MethodType.FUNCTION
    is_async: bool = False
    docstring: str = ""
    annotations: dict[str, Any] = field(default_factory=dict)

    # Service contract information
    service_version: str = "1.0.0"
    stability_level: str = "stable"  # stable, beta, alpha, experimental
    deprecation_warning: str = ""

    # Performance and resource metadata
    expected_complexity: str = "O(1)"  # Big O notation
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    timeout_hint: int = 30  # seconds

    def __post_init__(self):
        """Post-initialization to validate and enhance metadata."""
        if not self.method_name:
            raise ValueError("method_name is required")

        if not isinstance(self.signature, inspect.Signature):
            raise TypeError("signature must be an inspect.Signature instance")

        # Extract parameter metadata from signature
        self._extract_parameter_metadata()

        # Validate type hints consistency
        self._validate_type_hints()

    def _extract_parameter_metadata(self):
        """Extract detailed parameter metadata from the signature."""
        for param_name, param in self.signature.parameters.items():
            kind_mapping = {
                inspect.Parameter.POSITIONAL_ONLY: ParameterKind.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD: ParameterKind.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.VAR_POSITIONAL: ParameterKind.VAR_POSITIONAL,
                inspect.Parameter.KEYWORD_ONLY: ParameterKind.KEYWORD_ONLY,
                inspect.Parameter.VAR_KEYWORD: ParameterKind.VAR_KEYWORD,
            }

            param_metadata = ParameterMetadata(
                name=param_name,
                type_hint=(
                    param.annotation
                    if param.annotation != inspect.Parameter.empty
                    else Any
                ),
                kind=kind_mapping[param.kind],
                default=param.default,
                annotation=param.annotation,
                has_default=param.default != inspect.Parameter.empty,
                is_optional=param.default != inspect.Parameter.empty
                or (
                    param.annotation != inspect.Parameter.empty
                    and hasattr(param.annotation, "__origin__")
                    and param.annotation.__origin__ is Union
                    and type(None) in param.annotation.__args__
                ),
            )

            self.parameter_metadata[param_name] = param_metadata

            # Also populate the parameters dict for backward compatibility
            if param.annotation != inspect.Parameter.empty:
                self.parameters[param_name] = param.annotation

    def _validate_type_hints(self):
        """Validate consistency between parameters and type_hints."""
        # Ensure type_hints includes all parameters
        for param_name, param_type in self.parameters.items():
            if param_name not in self.type_hints:
                self.type_hints[param_name] = param_type

        # Add return type to type_hints
        if self.signature.return_annotation != inspect.Signature.empty:
            self.return_type = self.signature.return_annotation
            self.type_hints["return"] = self.return_type

    def get_required_parameters(self) -> list[str]:
        """Get list of required (non-optional) parameter names."""
        return [
            name
            for name, metadata in self.parameter_metadata.items()
            if not metadata.is_optional
            and metadata.kind != ParameterKind.VAR_POSITIONAL
            and metadata.kind != ParameterKind.VAR_KEYWORD
        ]

    def get_optional_parameters(self) -> list[str]:
        """Get list of optional parameter names."""
        return [
            name
            for name, metadata in self.parameter_metadata.items()
            if metadata.is_optional
        ]

    def has_capability(self, capability: str) -> bool:
        """Check if this method provides a specific capability."""
        return capability in self.capabilities

    def is_compatible_with(self, other: "MethodMetadata") -> bool:
        """Check if this method is compatible with another method signature."""
        if self.method_name != other.method_name:
            return False

        # Check parameter compatibility
        our_required = set(self.get_required_parameters())
        other_required = set(other.get_required_parameters())

        # We're compatible if we can fulfill all of other's required parameters
        return our_required.issuperset(other_required)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation for serialization."""
        return {
            "method_name": self.method_name,
            "capabilities": self.capabilities,
            "return_type": str(self.return_type),
            "parameters": {k: str(v) for k, v in self.parameters.items()},
            "type_hints": {k: str(v) for k, v in self.type_hints.items()},
            "method_type": self.method_type.value,
            "is_async": self.is_async,
            "docstring": self.docstring,
            "service_version": self.service_version,
            "stability_level": self.stability_level,
            "deprecation_warning": self.deprecation_warning,
            "expected_complexity": self.expected_complexity,
            "resource_requirements": self.resource_requirements,
            "timeout_hint": self.timeout_hint,
            "required_parameters": self.get_required_parameters(),
            "optional_parameters": self.get_optional_parameters(),
        }


@dataclass
class ServiceContract:
    """
    Service contract containing multiple method metadata entries.

    Represents the complete API contract for a service or agent,
    including all available methods and their signatures.
    """

    service_name: str
    service_version: str = "1.0.0"
    methods: dict[str, MethodMetadata] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    description: str = ""

    # Contract metadata
    contract_version: str = "1.0.0"
    compatibility_level: str = "strict"  # strict, relaxed, permissive

    def add_method(self, method_metadata: MethodMetadata):
        """Add a method to the service contract."""
        self.methods[method_metadata.method_name] = method_metadata

        # Update service capabilities
        for capability in method_metadata.capabilities:
            if capability not in self.capabilities:
                self.capabilities.append(capability)

    def get_method(self, method_name: str) -> MethodMetadata | None:
        """Get method metadata by name."""
        return self.methods.get(method_name)

    def has_capability(self, capability: str) -> bool:
        """Check if this service provides a specific capability."""
        return capability in self.capabilities

    def is_compatible_with(self, other: "ServiceContract") -> bool:
        """Check if this contract is compatible with another contract."""
        # Basic compatibility check
        if self.compatibility_level == "strict":
            return (
                self.service_name == other.service_name
                and self.service_version == other.service_version
            )

        # Check if we can fulfill all methods in the other contract
        for method_name, other_method in other.methods.items():
            our_method = self.get_method(method_name)
            if not our_method or not our_method.is_compatible_with(other_method):
                return False

        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation for serialization."""
        return {
            "service_name": self.service_name,
            "service_version": self.service_version,
            "capabilities": self.capabilities,
            "description": self.description,
            "contract_version": self.contract_version,
            "compatibility_level": self.compatibility_level,
            "methods": {
                name: method.to_dict() for name, method in self.methods.items()
            },
        }
