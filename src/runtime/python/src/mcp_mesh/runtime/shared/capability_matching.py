"""Capability Matching and Scoring Engine.

Implementation of semantic capability matching with hierarchy support,
complex query evaluation, and compatibility scoring.
"""

import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from mcp_mesh import (
    AgentInfo,
    CapabilityHierarchy,
    CapabilityMatchingProtocol,
    CapabilityMetadata,
    CapabilityQuery,
    CompatibilityScore,
    MeshAgentMetadata,
    QueryOperator,
    Requirements,
)


class CapabilityMatchingEngine:
    """Advanced capability matching and scoring engine."""

    def __init__(self):
        self.logger = logging.getLogger("capability_matching")
        self._capability_cache: dict[str, CapabilityMetadata] = {}
        self._hierarchy_cache: CapabilityHierarchy | None = None

    def score_capability_match(
        self, required: CapabilityMetadata, provided: CapabilityMetadata
    ) -> float:
        """Score the match between required and provided capabilities."""
        # Start with exact name match
        if required.name == provided.name:
            # Check version compatibility
            version_score = self._score_version_compatibility(
                required.version, provided.version
            )
            return version_score

        # Semantic similarity scoring
        name_similarity = self._calculate_name_similarity(required.name, provided.name)

        # Tag-based similarity
        tag_similarity = self._calculate_tag_similarity(required.tags, provided.tags)

        # Parameter compatibility
        param_compatibility = self._calculate_parameter_compatibility(
            required.parameters, provided.parameters
        )

        # Performance compatibility
        perf_compatibility = self._calculate_performance_compatibility(
            required.performance_metrics, provided.performance_metrics
        )

        # Weighted average
        weights = {
            "name": 0.4,
            "tags": 0.2,
            "parameters": 0.2,
            "performance": 0.2,
        }

        score = (
            weights["name"] * name_similarity
            + weights["tags"] * tag_similarity
            + weights["parameters"] * param_compatibility
            + weights["performance"] * perf_compatibility
        )

        return min(score, 1.0)

    def build_capability_hierarchy(
        self, capabilities: list[CapabilityMetadata]
    ) -> CapabilityHierarchy:
        """Build hierarchical structure from capabilities."""
        inheritance_map: dict[str, list[str]] = {}
        root_capabilities = []

        # Build inheritance mapping
        for capability in capabilities:
            self._capability_cache[capability.name] = capability

            if not capability.parent_capabilities:
                root_capabilities.append(capability)

            for parent in capability.parent_capabilities:
                if parent not in inheritance_map:
                    inheritance_map[parent] = []
                inheritance_map[parent].append(capability.name)

        hierarchy = CapabilityHierarchy(
            root_capabilities=root_capabilities, inheritance_map=inheritance_map
        )

        self._hierarchy_cache = hierarchy
        return hierarchy

    def evaluate_query(
        self, query: CapabilityQuery, agent_metadata: MeshAgentMetadata
    ) -> bool:
        """Evaluate query against agent metadata."""
        return self._evaluate_query_recursive(query, agent_metadata)

    def compute_compatibility_score(
        self, agent_info: AgentInfo, requirements: Requirements
    ) -> CompatibilityScore:
        """Compute comprehensive compatibility score."""
        # Initialize score components
        capability_score = self._score_capability_requirements(
            agent_info.agent_metadata.capabilities, requirements
        )

        performance_score = self._score_performance_requirements(
            agent_info, requirements
        )

        security_score = self._score_security_requirements(
            agent_info.agent_metadata, requirements
        )

        availability_score = self._score_availability_requirements(
            agent_info, requirements
        )

        # Calculate overall score with weights
        weights = {
            "capability": 0.4,
            "performance": 0.25,
            "security": 0.2,
            "availability": 0.15,
        }

        overall_score = (
            weights["capability"] * capability_score
            + weights["performance"] * performance_score
            + weights["security"] * security_score
            + weights["availability"] * availability_score
        )

        # Build detailed breakdown
        detailed_breakdown = {
            "capability_score": capability_score,
            "performance_score": performance_score,
            "security_score": security_score,
            "availability_score": availability_score,
            "weights": weights,
        }

        # Find missing and matching capabilities
        missing_capabilities = self._find_missing_capabilities(
            agent_info.agent_metadata.capabilities, requirements
        )

        matching_capabilities = self._find_matching_capabilities(
            agent_info.agent_metadata.capabilities, requirements
        )

        # Generate recommendations
        recommendations = self._generate_recommendations(
            agent_info, requirements, capability_score, performance_score
        )

        return CompatibilityScore(
            agent_id=agent_info.agent_id,
            overall_score=overall_score,
            capability_score=capability_score,
            performance_score=performance_score,
            security_score=security_score,
            availability_score=availability_score,
            detailed_breakdown=detailed_breakdown,
            missing_capabilities=missing_capabilities,
            matching_capabilities=matching_capabilities,
            recommendations=recommendations,
            computed_at=datetime.now(),
        )

    def _evaluate_query_recursive(
        self, query: CapabilityQuery, agent_metadata: MeshAgentMetadata
    ) -> bool:
        """Recursively evaluate query against agent metadata."""
        if query.operator == QueryOperator.AND:
            return all(
                self._evaluate_query_recursive(subquery, agent_metadata)
                for subquery in query.subqueries
            )

        elif query.operator == QueryOperator.OR:
            return any(
                self._evaluate_query_recursive(subquery, agent_metadata)
                for subquery in query.subqueries
            )

        elif query.operator == QueryOperator.NOT:
            if query.subqueries:
                return not self._evaluate_query_recursive(
                    query.subqueries[0], agent_metadata
                )
            return False

        elif query.operator == QueryOperator.CONTAINS:
            return self._evaluate_contains_query(query, agent_metadata)

        elif query.operator == QueryOperator.MATCHES:
            return self._evaluate_matches_query(query, agent_metadata)

        elif query.operator == QueryOperator.EQUALS:
            return self._evaluate_equals_query(query, agent_metadata)

        elif query.operator in [QueryOperator.GREATER_THAN, QueryOperator.LESS_THAN]:
            return self._evaluate_comparison_query(query, agent_metadata)

        return False

    def _evaluate_contains_query(
        self, query: CapabilityQuery, agent_metadata: MeshAgentMetadata
    ) -> bool:
        """Evaluate CONTAINS query."""
        if not query.field or query.value is None:
            return False

        if query.field == "capabilities":
            capability_names = [cap.name for cap in agent_metadata.capabilities]
            if isinstance(query.value, str):
                return query.value in capability_names
            elif isinstance(query.value, list):
                return any(val in capability_names for val in query.value)

        elif query.field == "tags":
            all_tags = set()
            for cap in agent_metadata.capabilities:
                all_tags.update(cap.tags)
            all_tags.update(agent_metadata.tags)

            if isinstance(query.value, str):
                return query.value in all_tags
            elif isinstance(query.value, list):
                return any(val in all_tags for val in query.value)

        return False

    def _evaluate_matches_query(
        self, query: CapabilityQuery, agent_metadata: MeshAgentMetadata
    ) -> bool:
        """Evaluate MATCHES query with pattern matching."""
        if not query.field or query.value is None:
            return False

        pattern = str(query.value)

        if query.field == "name":
            return bool(re.search(pattern, agent_metadata.name, re.IGNORECASE))

        elif query.field == "description":
            description = agent_metadata.description or ""
            return bool(re.search(pattern, description, re.IGNORECASE))

        elif query.field == "capabilities":
            capability_names = [cap.name for cap in agent_metadata.capabilities]
            return any(
                re.search(pattern, name, re.IGNORECASE) for name in capability_names
            )

        return False

    def _evaluate_equals_query(
        self, query: CapabilityQuery, agent_metadata: MeshAgentMetadata
    ) -> bool:
        """Evaluate EQUALS query."""
        if not query.field or query.value is None:
            return False

        if query.field == "name":
            return agent_metadata.name == query.value

        elif query.field == "version":
            return agent_metadata.version == query.value

        elif query.field == "security_context":
            return agent_metadata.security_context == query.value

        return False

    def _evaluate_comparison_query(
        self, query: CapabilityQuery, agent_metadata: MeshAgentMetadata
    ) -> bool:
        """Evaluate comparison queries (GT, LT)."""
        if not query.field or query.value is None:
            return False

        try:
            query_value = float(query.value)
        except (ValueError, TypeError):
            return False

        if query.field in agent_metadata.performance_profile:
            agent_value = agent_metadata.performance_profile[query.field]
            if query.operator == QueryOperator.GREATER_THAN:
                return agent_value > query_value
            elif query.operator == QueryOperator.LESS_THAN:
                return agent_value < query_value

        return False

    def _score_version_compatibility(self, required: str, provided: str) -> float:
        """Score version compatibility."""
        try:
            req_parts = [int(x) for x in required.split(".")]
            prov_parts = [int(x) for x in provided.split(".")]

            # Pad shorter version with zeros
            max_len = max(len(req_parts), len(prov_parts))
            req_parts.extend([0] * (max_len - len(req_parts)))
            prov_parts.extend([0] * (max_len - len(prov_parts)))

            # Major version must match or be higher
            if prov_parts[0] < req_parts[0]:
                return 0.0
            elif prov_parts[0] > req_parts[0]:
                return 1.0

            # Same major version, check minor and patch
            score = 1.0
            for i in range(1, len(req_parts)):
                if prov_parts[i] < req_parts[i]:
                    score *= 0.8  # Penalize lower versions
                elif prov_parts[i] > req_parts[i]:
                    score *= 1.0  # No penalty for higher versions

            return score

        except (ValueError, IndexError):
            # Fallback to string similarity
            return SequenceMatcher(None, required, provided).ratio()

    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate semantic similarity between capability names."""
        # Exact match
        if name1 == name2:
            return 1.0

        # Case-insensitive match
        if name1.lower() == name2.lower():
            return 0.95

        # String similarity
        similarity = SequenceMatcher(None, name1.lower(), name2.lower()).ratio()

        # Bonus for common patterns
        if any(word in name2.lower() for word in name1.lower().split("_")):
            similarity = min(similarity + 0.1, 1.0)

        return similarity

    def _calculate_tag_similarity(self, tags1: list[str], tags2: list[str]) -> float:
        """Calculate similarity based on tags."""
        if not tags1 and not tags2:
            return 1.0

        if not tags1 or not tags2:
            return 0.0

        set1 = {tag.lower() for tag in tags1}
        set2 = {tag.lower() for tag in tags2}

        intersection = set1.intersection(set2)
        union = set1.union(set2)

        return len(intersection) / len(union) if union else 0.0

    def _calculate_parameter_compatibility(
        self, params1: dict[str, Any], params2: dict[str, Any]
    ) -> float:
        """Calculate parameter compatibility."""
        if not params1 and not params2:
            return 1.0

        if not params1 or not params2:
            return 0.5  # Partial compatibility

        # Check for matching parameters
        matching_params = 0
        total_params = len(set(params1.keys()).union(set(params2.keys())))

        for key in params1:
            if key in params2:
                # Simple value comparison
                if params1[key] == params2[key]:
                    matching_params += 1
                else:
                    # Partial match for numeric values
                    try:
                        val1 = float(params1[key])
                        val2 = float(params2[key])
                        if abs(val1 - val2) / max(val1, val2, 1) < 0.1:
                            matching_params += 0.5
                    except (ValueError, TypeError, ZeroDivisionError):
                        pass

        return matching_params / total_params if total_params > 0 else 1.0

    def _calculate_performance_compatibility(
        self, perf1: dict[str, float], perf2: dict[str, float]
    ) -> float:
        """Calculate performance compatibility."""
        if not perf1 and not perf2:
            return 1.0

        if not perf1 or not perf2:
            return 0.7  # Neutral score when one is missing

        # Compare common metrics
        common_metrics = set(perf1.keys()).intersection(set(perf2.keys()))
        if not common_metrics:
            return 0.7

        total_score = 0.0
        for metric in common_metrics:
            val1, val2 = perf1[metric], perf2[metric]
            if val1 == 0 and val2 == 0:
                total_score += 1.0
            elif val1 == 0 or val2 == 0:
                total_score += 0.5
            else:
                # Performance ratio score
                ratio = min(val1, val2) / max(val1, val2)
                total_score += ratio

        return total_score / len(common_metrics)

    def _score_capability_requirements(
        self, capabilities: list[CapabilityMetadata], requirements: Requirements
    ) -> float:
        """Score capability requirements fulfillment."""
        if not requirements.required_capabilities:
            return 1.0

        capability_names = [cap.name for cap in capabilities]

        # Check required capabilities
        required_met = 0
        for required_cap in requirements.required_capabilities:
            if required_cap in capability_names:
                required_met += 1
            else:
                # Check for semantic matches
                best_match_score = 0.0
                for cap in capabilities:
                    score = self._calculate_name_similarity(required_cap, cap.name)
                    best_match_score = max(best_match_score, score)
                required_met += best_match_score

        required_score = required_met / len(requirements.required_capabilities)

        # Bonus for preferred capabilities
        preferred_met = 0
        if requirements.preferred_capabilities:
            for preferred_cap in requirements.preferred_capabilities:
                if preferred_cap in capability_names:
                    preferred_met += 1

            preferred_score = preferred_met / len(requirements.preferred_capabilities)
            # Weight required more heavily than preferred
            return 0.8 * required_score + 0.2 * preferred_score

        return required_score

    def _score_performance_requirements(
        self, agent_info: AgentInfo, requirements: Requirements
    ) -> float:
        """Score performance requirements."""
        if not requirements.performance_requirements:
            return 1.0

        performance_scores = []

        # Check latency requirement
        if requirements.max_latency_ms is not None:
            if agent_info.response_time_ms is not None:
                if agent_info.response_time_ms <= requirements.max_latency_ms:
                    performance_scores.append(1.0)
                else:
                    # Degraded score based on how much it exceeds
                    ratio = requirements.max_latency_ms / agent_info.response_time_ms
                    performance_scores.append(max(ratio, 0.0))
            else:
                performance_scores.append(0.5)  # Unknown latency

        # Check other performance metrics
        agent_performance = agent_info.agent_metadata.performance_profile
        for metric, required_value in requirements.performance_requirements.items():
            if metric in agent_performance:
                agent_value = agent_performance[metric]
                # Assume higher values are better for most metrics
                if agent_value >= required_value:
                    performance_scores.append(1.0)
                else:
                    performance_scores.append(agent_value / required_value)
            else:
                performance_scores.append(0.0)  # Missing metric

        return (
            sum(performance_scores) / len(performance_scores)
            if performance_scores
            else 1.0
        )

    def _score_security_requirements(
        self, agent_metadata: MeshAgentMetadata, requirements: Requirements
    ) -> float:
        """Score security requirements."""
        if not requirements.security_requirements:
            return 1.0

        security_scores = []

        for (
            requirement_key,
            required_value,
        ) in requirements.security_requirements.items():
            if requirement_key == "security_context":
                if agent_metadata.security_context == required_value:
                    security_scores.append(1.0)
                else:
                    security_scores.append(0.0)

            # Check capability-level security
            else:
                capability_security_met = False
                for cap in agent_metadata.capabilities:
                    if (
                        hasattr(cap, requirement_key)
                        and getattr(cap, requirement_key) == required_value
                    ):
                        capability_security_met = True
                        break

                security_scores.append(1.0 if capability_security_met else 0.0)

        return sum(security_scores) / len(security_scores) if security_scores else 1.0

    def _score_availability_requirements(
        self, agent_info: AgentInfo, requirements: Requirements
    ) -> float:
        """Score availability requirements."""
        if requirements.min_availability is None:
            return agent_info.availability

        if agent_info.availability >= requirements.min_availability:
            return 1.0
        else:
            return agent_info.availability / requirements.min_availability

    def _find_missing_capabilities(
        self, capabilities: list[CapabilityMetadata], requirements: Requirements
    ) -> list[str]:
        """Find missing required capabilities."""
        capability_names = [cap.name for cap in capabilities]
        missing = []

        for required_cap in requirements.required_capabilities:
            if required_cap not in capability_names:
                # Check if any capability provides this through inheritance
                found_inherited = False
                if self._hierarchy_cache:
                    for cap_name in capability_names:
                        if self._hierarchy_cache.is_compatible(required_cap, cap_name):
                            found_inherited = True
                            break

                if not found_inherited:
                    missing.append(required_cap)

        return missing

    def _find_matching_capabilities(
        self, capabilities: list[CapabilityMetadata], requirements: Requirements
    ) -> list[str]:
        """Find matching capabilities."""
        capability_names = [cap.name for cap in capabilities]
        matching = []

        all_required = (
            requirements.required_capabilities + requirements.preferred_capabilities
        )

        for required_cap in all_required:
            if required_cap in capability_names:
                matching.append(required_cap)
            elif self._hierarchy_cache:
                # Check inheritance
                for cap_name in capability_names:
                    if self._hierarchy_cache.is_compatible(required_cap, cap_name):
                        matching.append(cap_name)
                        break

        return matching

    def _generate_recommendations(
        self,
        agent_info: AgentInfo,
        requirements: Requirements,
        capability_score: float,
        performance_score: float,
    ) -> list[str]:
        """Generate improvement recommendations."""
        recommendations = []

        if capability_score < 0.8:
            missing = self._find_missing_capabilities(
                agent_info.agent_metadata.capabilities, requirements
            )
            if missing:
                recommendations.append(
                    f"Add missing capabilities: {', '.join(missing[:3])}"
                )

        if performance_score < 0.7:
            if (
                requirements.max_latency_ms
                and agent_info.response_time_ms
                and agent_info.response_time_ms > requirements.max_latency_ms
            ):
                recommendations.append("Improve response time performance")

            recommendations.append("Optimize performance metrics")

        if agent_info.availability < 0.9:
            recommendations.append("Improve service availability")

        if agent_info.success_rate < 0.95:
            recommendations.append("Improve operation success rate")

        return recommendations


# Implement the protocol
class CapabilityMatcher(CapabilityMatchingEngine, CapabilityMatchingProtocol):
    """Protocol-compliant capability matcher."""

    pass
