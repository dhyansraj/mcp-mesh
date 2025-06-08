"""
Unified Dependency Resolution Types

This module provides type definitions and interfaces for the unified dependency
resolver that supports all 3 patterns simultaneously:

1. String dependencies: "legacy_auth" (existing from Week 1, Day 4)
2. Protocol interfaces: AuthService (traditional interface-based)
3. Concrete classes: OAuth2AuthService (new auto-discovery pattern)
"""

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    TypeVar,
)

T = TypeVar("T")


class DependencyPattern(Enum):
    """Types of dependency patterns supported."""

    STRING = "string"  # Legacy string dependencies like "legacy_auth"
    PROTOCOL = "protocol"  # Protocol/interface-based like AuthService
    CONCRETE = "concrete"  # Concrete class-based like OAuth2AuthService


@dataclass
class DependencySpecification:
    """Specification for a dependency resolution request."""

    pattern: DependencyPattern
    identifier: str | type  # String for STRING pattern, Type for others
    parameter_name: str | None = None  # Parameter name in function signature
    type_hint: type | None = None  # Type hint from function annotation
    default_value: Any = None  # Default value if provided
    is_optional: bool = False  # Whether dependency is optional

    @classmethod
    def from_string(
        cls,
        dependency: str,
        parameter_name: str | None = None,
        type_hint: type | None = None,
        default_value: Any = None,
        is_optional: bool = False,
    ) -> "DependencySpecification":
        """Create specification for string dependency."""
        return cls(
            pattern=DependencyPattern.STRING,
            identifier=dependency,
            parameter_name=parameter_name,
            type_hint=type_hint,
            default_value=default_value,
            is_optional=is_optional,
        )

    @classmethod
    def from_protocol(
        cls,
        protocol_type: type,
        parameter_name: str | None = None,
        default_value: Any = None,
        is_optional: bool = False,
    ) -> "DependencySpecification":
        """Create specification for protocol dependency."""
        return cls(
            pattern=DependencyPattern.PROTOCOL,
            identifier=protocol_type,
            parameter_name=parameter_name,
            type_hint=protocol_type,
            default_value=default_value,
            is_optional=is_optional,
        )

    @classmethod
    def from_concrete(
        cls,
        concrete_type: type,
        parameter_name: str | None = None,
        default_value: Any = None,
        is_optional: bool = False,
    ) -> "DependencySpecification":
        """Create specification for concrete class dependency."""
        return cls(
            pattern=DependencyPattern.CONCRETE,
            identifier=concrete_type,
            parameter_name=parameter_name,
            type_hint=concrete_type,
            default_value=default_value,
            is_optional=is_optional,
        )

    @property
    def display_name(self) -> str:
        """Get display name for the dependency."""
        if self.pattern == DependencyPattern.STRING:
            return str(self.identifier)
        elif hasattr(self.identifier, "__name__"):
            return self.identifier.__name__
        else:
            return str(self.identifier)

    def is_type_compatible(self, other_type: type) -> bool:
        """Check if this dependency is compatible with another type."""
        if self.pattern == DependencyPattern.STRING:
            # String dependencies are resolved by name, compatibility is runtime
            return True

        if self.type_hint is None:
            return False

        try:
            # Check if other_type implements this dependency's interface
            if self.pattern == DependencyPattern.PROTOCOL:
                # For protocols, check structural compatibility
                return isinstance(other_type, type) and issubclass(
                    other_type, self.type_hint
                )
            elif self.pattern == DependencyPattern.CONCRETE:
                # For concrete types, check inheritance
                return isinstance(other_type, type) and (
                    other_type == self.type_hint
                    or issubclass(other_type, self.type_hint)
                    or issubclass(self.type_hint, other_type)
                )
        except TypeError:
            # Type checking failed, not compatible
            return False

        return False


@dataclass
class DependencyResolutionResult:
    """Result of dependency resolution."""

    specification: DependencySpecification
    instance: Any | None
    success: bool
    resolution_method: str  # "remote_proxy", "local_instance", "cached", etc.
    resolution_time_ms: float
    error: Exception | None = None
    fallback_used: bool = False

    @property
    def failed(self) -> bool:
        """Check if resolution failed."""
        return not self.success or self.instance is None


class UnifiedDependencyResolver(ABC):
    """
    Abstract interface for unified dependency resolution.

    This resolver must support all 3 dependency patterns:
    1. String dependencies (legacy)
    2. Protocol interfaces
    3. Concrete classes
    """

    @abstractmethod
    async def resolve_dependency(
        self,
        specification: DependencySpecification,
        context: dict[str, Any] | None = None,
    ) -> DependencyResolutionResult:
        """
        Resolve a dependency based on its specification.

        Args:
            specification: Dependency specification
            context: Optional resolution context

        Returns:
            Resolution result with instance or error
        """
        pass

    @abstractmethod
    def can_resolve(self, specification: DependencySpecification) -> bool:
        """
        Check if this resolver can handle the given dependency specification.

        Args:
            specification: Dependency specification to check

        Returns:
            True if this resolver can handle the specification
        """
        pass

    @abstractmethod
    async def resolve_multiple(
        self,
        specifications: list[DependencySpecification],
        context: dict[str, Any] | None = None,
    ) -> list[DependencyResolutionResult]:
        """
        Resolve multiple dependencies efficiently.

        Args:
            specifications: List of dependency specifications
            context: Optional resolution context

        Returns:
            List of resolution results in same order as specifications
        """
        pass

    @property
    @abstractmethod
    def resolver_name(self) -> str:
        """Get the name of this resolver."""
        pass


@dataclass
class DependencyValidationError:
    """Error from dependency validation."""

    specification: DependencySpecification | None
    error_type: str
    message: str
    suggestions: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of dependency validation."""

    is_valid: bool
    errors: list[DependencyValidationError] = field(default_factory=list)
    validated_count: int = 0
    error_count: int = 0


class DependencyValidator(ABC):
    """Interface for validating dependency specifications."""

    @abstractmethod
    def validate_specification(
        self, specification: DependencySpecification
    ) -> list[DependencyValidationError]:
        """
        Validate a dependency specification.

        Args:
            specification: Specification to validate

        Returns:
            List of validation errors (empty if valid)
        """
        pass

    @abstractmethod
    def validate_specifications(
        self, specifications: list[DependencySpecification]
    ) -> dict[str, list[DependencyValidationError]]:
        """
        Validate multiple dependency specifications.

        Args:
            specifications: List of specifications to validate

        Returns:
            Dictionary mapping specification display names to validation errors
        """
        pass


class DependencyAnalyzer:
    """Utility class for analyzing dependencies from various sources."""

    @staticmethod
    def analyze_dependencies_list(
        dependencies: list[str | type],
        function_signature: inspect.Signature | None = None,
    ) -> list[DependencySpecification]:
        """
        Analyze a list of dependencies to create specifications.

        Args:
            dependencies: List of dependencies (strings, protocols, or concrete types)
            function_signature: Optional function signature for parameter mapping

        Returns:
            List of dependency specifications
        """
        specifications = []

        # Extract parameter info from signature if available
        param_info = {}
        if function_signature:
            for param_name, param in function_signature.parameters.items():
                if param_name != "self":  # Skip self parameter
                    param_info[param_name] = {
                        "type_hint": (
                            param.annotation
                            if param.annotation != inspect.Parameter.empty
                            else None
                        ),
                        "default": (
                            param.default
                            if param.default != inspect.Parameter.empty
                            else None
                        ),
                        "is_optional": param.default != inspect.Parameter.empty,
                    }

        for dependency in dependencies:
            spec = DependencyAnalyzer._create_specification(dependency, param_info)
            specifications.append(spec)

        return specifications

    @staticmethod
    def _create_specification(
        dependency: str | type, param_info: dict[str, dict[str, Any]]
    ) -> DependencySpecification:
        """Create a dependency specification from a dependency item."""

        if isinstance(dependency, str):
            # String dependency pattern
            # Try to find matching parameter
            parameter_name = None
            type_hint = None
            default_value = None
            is_optional = False

            # Look for parameter with matching name or containing the dependency string
            for param_name, info in param_info.items():
                if (
                    param_name == dependency
                    or dependency.lower() in param_name.lower()
                    or param_name.lower() in dependency.lower()
                ):
                    parameter_name = param_name
                    type_hint = info["type_hint"]
                    default_value = info["default"]
                    is_optional = info["is_optional"]
                    break

            return DependencySpecification.from_string(
                dependency=dependency,
                parameter_name=parameter_name,
                type_hint=type_hint,
                default_value=default_value,
                is_optional=is_optional,
            )

        elif inspect.isclass(dependency):
            # Type-based dependency (protocol or concrete)
            dependency_name = dependency.__name__

            # Find matching parameter by type or name
            parameter_name = None
            default_value = None
            is_optional = False

            for param_name, info in param_info.items():
                type_hint = info["type_hint"]

                # Check type compatibility
                if type_hint and DependencyAnalyzer._types_compatible(
                    dependency, type_hint
                ):
                    parameter_name = param_name
                    default_value = info["default"]
                    is_optional = info["is_optional"]
                    break

                # Check name similarity
                if (
                    param_name.lower() == dependency_name.lower()
                    or dependency_name.lower() in param_name.lower()
                    or param_name.lower() in dependency_name.lower()
                ):
                    parameter_name = param_name
                    default_value = info["default"]
                    is_optional = info["is_optional"]
                    # Don't break - type match is preferred

            # Determine if it's a protocol or concrete class
            if DependencyAnalyzer._is_protocol(dependency):
                return DependencySpecification.from_protocol(
                    protocol_type=dependency,
                    parameter_name=parameter_name,
                    default_value=default_value,
                    is_optional=is_optional,
                )
            else:
                return DependencySpecification.from_concrete(
                    concrete_type=dependency,
                    parameter_name=parameter_name,
                    default_value=default_value,
                    is_optional=is_optional,
                )

        else:
            # Unsupported dependency type - treat as string
            return DependencySpecification.from_string(
                dependency=str(dependency),
                parameter_name=None,
                type_hint=None,
                default_value=None,
                is_optional=False,
            )

    @staticmethod
    def _types_compatible(type1: type, type2: type) -> bool:
        """Check if two types are compatible."""
        try:
            if type1 == type2:
                return True

            if inspect.isclass(type1) and inspect.isclass(type2):
                return issubclass(type1, type2) or issubclass(type2, type1)

            return False
        except TypeError:
            return False

    @staticmethod
    def _is_protocol(cls: type) -> bool:
        """Check if a class is a Protocol."""
        try:
            # Check for Protocol marker
            if hasattr(cls, "_is_protocol"):
                return cls._is_protocol

            # Check if it inherits from Protocol
            return hasattr(cls, "__annotations__") and any(
                hasattr(base, "_is_protocol") and base._is_protocol
                for base in getattr(cls, "__mro__", [])
            )
        except:
            return False


# Type aliases for convenience
DependencyList = list[str | type]
DependencyMap = dict[str, Any]
DependencyContext = dict[str, Any]
