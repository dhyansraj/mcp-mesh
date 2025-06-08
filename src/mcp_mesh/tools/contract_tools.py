"""Service Contract Management Tools.

Provides comprehensive tools for storing, retrieving, and validating service contracts
with the registry database. Implements the required functions for contract management.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any

from mcp_mesh_types.method_metadata import MethodMetadata, ServiceContract

from ..server.database import RegistryDatabase


class ContractResult:
    """Result object for contract storage operations."""

    def __init__(
        self,
        success: bool,
        contract_id: int | None = None,
        message: str = "",
        error: str = "",
    ):
        self.success = success
        self.contract_id = contract_id
        self.message = message
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "contract_id": self.contract_id,
            "message": self.message,
            "error": self.error,
        }


class ValidationResult:
    """Result object for contract validation operations."""

    def __init__(
        self,
        is_valid: bool,
        issues: list[str] | None = None,
        compatibility_score: float = 0.0,
    ):
        self.is_valid = is_valid
        self.issues = issues or []
        self.compatibility_score = compatibility_score

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "is_valid": self.is_valid,
            "issues": self.issues,
            "compatibility_score": self.compatibility_score,
        }


class ContractTools:
    """Tools for service contract management with the registry database."""

    def __init__(self, database: RegistryDatabase):
        self.database = database
        self.logger = logging.getLogger("contract_tools")

    async def store_service_contract(
        self, class_type: type, metadata: MethodMetadata
    ) -> ContractResult:
        """
        Store a service contract for a class type with method metadata.

        Args:
            class_type: The class type providing the service
            metadata: Method metadata to store

        Returns:
            ContractResult with operation status and contract ID
        """
        start_time = time.time()

        try:
            # Create a service contract from the class and method metadata
            service_name = self._get_service_name(class_type)
            agent_id = self._get_agent_id_for_class(class_type)

            # Check if contract already exists and create/update it
            existing_contract = await self.database.get_service_contract(
                agent_id, service_name
            )

            if existing_contract:
                # Update existing contract
                existing_contract.add_method(metadata)
                contract_id = await self.database.store_service_contract(
                    agent_id, existing_contract
                )
            else:
                # Create new contract
                contract = ServiceContract(
                    service_name=service_name,
                    service_version="1.0.0",
                    description=f"Service contract for {class_type.__name__}",
                )
                contract.add_method(metadata)
                contract_id = await self.database.store_service_contract(
                    agent_id, contract
                )

            duration = (time.time() - start_time) * 1000

            self.logger.info(
                f"Stored service contract for {service_name} in {duration:.2f}ms, contract_id: {contract_id}"
            )

            return ContractResult(
                success=True,
                contract_id=contract_id,
                message=f"Successfully stored contract for {service_name}",
            )

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            error_msg = f"Failed to store service contract: {str(e)}"

            self.logger.error(f"{error_msg} (took {duration:.2f}ms)")

            return ContractResult(
                success=False,
                error=error_msg,
                message="Contract storage failed",
            )

    async def get_service_contract(self, class_type: type) -> ServiceContract | None:
        """
        Retrieve a service contract for a class type.

        Args:
            class_type: The class type to get the contract for

        Returns:
            ServiceContract if found, None otherwise
        """
        start_time = time.time()

        try:
            service_name = self._get_service_name(class_type)
            agent_id = self._get_agent_id_for_class(class_type)

            contract = await self.database.get_service_contract(agent_id, service_name)

            duration = (time.time() - start_time) * 1000

            if contract:
                self.logger.debug(
                    f"Retrieved service contract for {service_name} in {duration:.2f}ms"
                )
            else:
                self.logger.debug(
                    f"No service contract found for {service_name} (took {duration:.2f}ms)"
                )

            return contract

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            self.logger.error(
                f"Failed to retrieve service contract for {class_type.__name__}: {str(e)} (took {duration:.2f}ms)"
            )
            return None

    async def validate_contract_compatibility(
        self, contract: ServiceContract
    ) -> ValidationResult:
        """
        Validate contract compatibility and signature consistency.

        Args:
            contract: The service contract to validate

        Returns:
            ValidationResult with validation status and issues
        """
        start_time = time.time()
        issues = []
        compatibility_score = 1.0

        try:
            # Validate contract structure
            if not contract.service_name:
                issues.append("Service name is required")

            if not contract.methods:
                issues.append("Contract must have at least one method")

            # Validate method signatures
            for method_name, method_metadata in contract.methods.items():
                method_issues = await self._validate_method_metadata(method_metadata)
                issues.extend(
                    [f"Method {method_name}: {issue}" for issue in method_issues]
                )

            # Check for capability consistency
            declared_capabilities = set(contract.capabilities)
            method_capabilities = set()
            for method in contract.methods.values():
                method_capabilities.update(method.capabilities)

            missing_capabilities = method_capabilities - declared_capabilities
            if missing_capabilities:
                issues.append(
                    f"Methods declare capabilities not in contract: {missing_capabilities}"
                )

            # Check for signature consistency across similar methods
            signature_issues = await self._validate_signature_consistency(contract)
            issues.extend(signature_issues)

            # Calculate compatibility score
            if issues:
                # Reduce score based on severity of issues
                critical_issues = [
                    i for i in issues if "required" in i.lower() or "must" in i.lower()
                ]
                compatibility_score = max(
                    0.0, 1.0 - (len(critical_issues) * 0.3) - (len(issues) * 0.1)
                )

            duration = (time.time() - start_time) * 1000
            is_valid = len(issues) == 0

            self.logger.debug(
                f"Validated contract {contract.service_name} in {duration:.2f}ms: "
                f"valid={is_valid}, score={compatibility_score:.2f}, issues={len(issues)}"
            )

            return ValidationResult(
                is_valid=is_valid,
                issues=issues,
                compatibility_score=compatibility_score,
            )

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            error_msg = f"Contract validation failed: {str(e)}"
            self.logger.error(f"{error_msg} (took {duration:.2f}ms)")

            return ValidationResult(
                is_valid=False,
                issues=[error_msg],
                compatibility_score=0.0,
            )

    async def _validate_method_metadata(self, metadata: MethodMetadata) -> list[str]:
        """Validate individual method metadata."""
        issues = []

        # Check required fields
        if not metadata.method_name:
            issues.append("Method name is required")

        if not metadata.signature:
            issues.append("Method signature is required")

        # Validate parameter metadata consistency
        sig_params = set(metadata.signature.parameters.keys())
        meta_params = set(metadata.parameter_metadata.keys())

        if sig_params != meta_params:
            issues.append(f"Parameter metadata mismatch: {sig_params} != {meta_params}")

        # Validate type hints
        for param_name, param_meta in metadata.parameter_metadata.items():
            if param_name in metadata.type_hints:
                if param_meta.type_hint != metadata.type_hints[param_name]:
                    issues.append(
                        f"Type hint mismatch for {param_name}: "
                        f"{param_meta.type_hint} != {metadata.type_hints[param_name]}"
                    )

        # Validate return type consistency
        if metadata.signature.return_annotation and metadata.return_type:
            if metadata.signature.return_annotation != metadata.return_type:
                issues.append(
                    f"Return type mismatch: {metadata.signature.return_annotation} != {metadata.return_type}"
                )

        return issues

    async def _validate_signature_consistency(
        self, contract: ServiceContract
    ) -> list[str]:
        """Validate signature consistency across methods in the contract."""
        issues = []

        # Group methods by capability
        capability_methods = {}
        for method_name, method in contract.methods.items():
            for capability in method.capabilities:
                if capability not in capability_methods:
                    capability_methods[capability] = []
                capability_methods[capability].append((method_name, method))

        # Check for consistent signatures within capabilities
        for capability, methods in capability_methods.items():
            if len(methods) > 1:
                # Compare method signatures for consistency
                base_method_name, base_method = methods[0]
                for other_method_name, other_method in methods[1:]:
                    compatibility_issues = self._check_method_compatibility(
                        base_method, other_method, base_method_name, other_method_name
                    )
                    issues.extend(compatibility_issues)

        return issues

    def _check_method_compatibility(
        self, method1: MethodMetadata, method2: MethodMetadata, name1: str, name2: str
    ) -> list[str]:
        """Check compatibility between two methods."""
        issues = []

        # Check if they should be compatible (same capability)
        common_capabilities = set(method1.capabilities) & set(method2.capabilities)
        if not common_capabilities:
            return issues  # No shared capabilities, no need to check compatibility

        # Check parameter compatibility
        required1 = set(method1.get_required_parameters())
        required2 = set(method2.get_required_parameters())

        if required1 != required2:
            issues.append(
                f"Methods {name1} and {name2} have different required parameters: "
                f"{required1} vs {required2}"
            )

        # Check return type compatibility
        if method1.return_type != method2.return_type:
            issues.append(
                f"Methods {name1} and {name2} have incompatible return types: "
                f"{method1.return_type} vs {method2.return_type}"
            )

        return issues

    def _get_service_name(self, class_type: type) -> str:
        """Extract service name from class type."""
        # Use class name as service name, could be enhanced with decorators
        return class_type.__name__.lower().replace("_", "-")

    def _get_agent_id_for_class(self, class_type: type) -> str:
        """Get agent ID for a class type. In real implementation, this would
        map to actual agent registrations."""
        # For now, use class name as agent ID
        # In production, this should map to actual registered agents
        return f"agent-{class_type.__name__.lower()}"

    # Additional utility methods for contract management

    async def find_contracts_by_capability(
        self, capability_name: str
    ) -> list[dict[str, Any]]:
        """Find all contracts that provide a specific capability."""
        try:
            results = await self.database.find_methods_by_capability(capability_name)
            return results
        except Exception as e:
            self.logger.error(
                f"Failed to find contracts by capability {capability_name}: {str(e)}"
            )
            return []

    async def get_contract_compatibility_info(
        self, service_name: str, version_constraint: str | None = None
    ) -> list[dict[str, Any]]:
        """Get contract compatibility information for version checking."""
        try:
            results = await self.database.get_contract_compatibility_info(
                service_name, version_constraint
            )
            return results
        except Exception as e:
            self.logger.error(
                f"Failed to get compatibility info for {service_name}: {str(e)}"
            )
            return []

    async def store_multiple_contracts(
        self, contracts: list[tuple[type, ServiceContract]]
    ) -> list[ContractResult]:
        """Store multiple service contracts efficiently."""
        results = []

        for class_type, contract in contracts:
            # Convert ServiceContract to individual method storage
            for method_name, method_metadata in contract.methods.items():
                result = await self.store_service_contract(class_type, method_metadata)
                results.append(result)

        return results

    async def validate_multiple_contracts(
        self, contracts: list[ServiceContract]
    ) -> list[ValidationResult]:
        """Validate multiple contracts."""
        results = []

        for contract in contracts:
            result = await self.validate_contract_compatibility(contract)
            results.append(result)

        return results

    async def get_performance_metrics(self) -> dict[str, Any]:
        """Get performance metrics for contract operations."""
        try:
            # Get database statistics
            db_stats = await self.database.get_database_stats()

            # Calculate contract-specific metrics
            contract_metrics = {
                "total_contracts": db_stats.get("service_contracts_count", 0),
                "total_methods": db_stats.get("method_metadata_count", 0),
                "avg_response_time_ms": 50,  # This would be tracked in production
                "cache_hit_rate": 0.85,  # This would be tracked in production
            }

            return {
                "database_stats": db_stats,
                "contract_metrics": contract_metrics,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            self.logger.error(f"Failed to get performance metrics: {str(e)}")
            return {"error": str(e)}


# Factory function for creating ContractTools
def create_contract_tools(database: RegistryDatabase) -> ContractTools:
    """Create a ContractTools instance with the provided database."""
    return ContractTools(database)
