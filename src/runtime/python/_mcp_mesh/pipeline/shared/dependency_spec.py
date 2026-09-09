"""Shared ``DependencySpec`` construction for every heartbeat path.

Issue #1571: the @mesh.tool heartbeat serialized the complete dependency
selector (tags, version, expected schema, match_mode, required) while the
@mesh.route and @mesh.a2a heartbeats each built their own reduced spec —
routes lost everything but the capability name, A2A lost ``required``,
``match_mode`` and the schema pair. Three copies meant three chances to
drift, so the construction (including the Issue #547 consumer-side schema
normalization) lives here and every path calls it.
"""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def cluster_strict_enabled() -> bool:
    """Issue #547 Phase 4: read MCP_MESH_SCHEMA_STRICT env var (cluster-wide knob).

    When true, WARN verdicts are promoted to BLOCK so ops can harden a whole
    cluster without changing every consumer.
    """
    return os.environ.get("MCP_MESH_SCHEMA_STRICT", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def should_refuse_startup(
    verdict: str, cluster_strict: bool, tool_strict: bool
) -> bool:
    """Issue #547 Phase 4: schema verdict policy.

    Composes two knobs:
      * cluster_strict (env MCP_MESH_SCHEMA_STRICT): promotes WARN→BLOCK.
      * tool_strict (per-tool output_schema_strict, default True): producer-side
        escape hatch. When False, BLOCK is demoted to WARN for that tool.

    Truth table:
      verdict=BLOCK + tool_strict=True  -> refuse
      verdict=BLOCK + tool_strict=False -> log only (override wins)
      verdict=WARN  + cluster_strict=True + tool_strict=True  -> refuse
      verdict=WARN  + cluster_strict=True + tool_strict=False -> log only
      verdict=WARN  + cluster_strict=False -> log only
      verdict=OK -> never refuse
    """
    if verdict == "BLOCK":
        return tool_strict
    if verdict == "WARN":
        return cluster_strict and tool_strict
    return False


def build_dependency_spec(
    core: Any, dep_info: dict[str, Any], *, cluster_strict: bool | None = None
) -> Any:
    """Build one Rust ``DependencySpec`` carrying the complete selector.

    Args:
        core: The ``mcp_mesh_core`` module (each pipeline resolves it lazily).
        dep_info: A validated dependency mapping as produced by
            ``mesh.decorators._validate_dependency_selector`` — ``capability``
            plus optional ``tags``, ``version``, ``required``, ``match_mode``
            and ``expected_schema_raw``.
        cluster_strict: MCP_MESH_SCHEMA_STRICT verdict promotion. Resolved
            from the environment when omitted; pass it explicitly when
            building a batch so the env is read once.

    Raises:
        RuntimeError: when schema normalization returns a verdict that the
            #547 policy refuses to start on.
    """
    if cluster_strict is None:
        cluster_strict = cluster_strict_enabled()

    capability = dep_info.get("capability", "")

    # Serialize tags to JSON to support nested arrays for OR alternatives
    # e.g., ["addition", ["python", "typescript"]] -> addition AND (python OR typescript)
    tags_json = json.dumps(dep_info.get("tags", []))

    # Issue #547 Phase 1D: normalize the consumer's expected schema via the
    # Rust normalizer (deferred from decorator time to keep import cheap and
    # consistent with producer-side normalization).
    expected_canonical: str | None = None
    expected_hash: str | None = None
    match_mode = dep_info.get("match_mode")
    expected_raw = dep_info.get("expected_schema_raw")
    if expected_raw is not None:
        try:
            normalize_fn = getattr(core, "normalize_schema_py", None)
            if normalize_fn is None:
                raise AttributeError("normalize_schema_py not in mcp_mesh_core")
            result = json.loads(normalize_fn(json.dumps(expected_raw), "python"))
            verdict = result.get("verdict", "OK")
            warnings_list = result.get("warnings") or []
            # Issue #547 Phase 4: there's no per-tool override on the consumer
            # side (the override is producer-side); use tool_strict=True so
            # cluster_strict still promotes WARN.
            if should_refuse_startup(verdict, cluster_strict, True):
                promoted = (
                    " (MCP_MESH_SCHEMA_STRICT=true upgraded WARN→BLOCK)"
                    if verdict == "WARN"
                    else ""
                )
                raise RuntimeError(
                    f"Schema normalization {verdict} for dependency on "
                    f"'{capability}'{promoted}: {warnings_list}. Cannot start agent."
                )
            if verdict == "WARN":
                logger.warning(
                    f"Schema WARN for dependency on '{capability}': {warnings_list}"
                )
            if result.get("canonical"):
                expected_canonical = json.dumps(result["canonical"])
                expected_hash = result.get("hash")
        except RuntimeError:
            raise
        except Exception as e:
            logger.warning(
                f"Could not normalize expected schema for dep '{capability}': {e}"
            )
            expected_canonical = None
            expected_hash = None

    return core.DependencySpec(
        capability=capability,
        tags=tags_json,
        version=dep_info.get("version"),
        expected_schema_canonical=expected_canonical,
        expected_schema_hash=expected_hash,
        match_mode=match_mode,
        # Issue #1249: opt-in strictness flag (default False). The registry
        # factors required edges into transitive capability availability.
        # Absent/false is omitted from the wire payload by the core's
        # skip_serializing_if.
        required=bool(dep_info.get("required", False)),
    )


def build_dependency_specs(
    core: Any,
    dep_infos: list[Any],
    *,
    cluster_strict: bool | None = None,
) -> list[Any]:
    """Build ``DependencySpec``s for a list of validated dependency mappings.

    Bare strings are accepted (and treated as a capability with no selector) so
    pre-#1571 callers that only ever held capability names keep working.

    The output is STRICTLY INDEX-ALIGNED with the input: one spec per entry,
    never dropped, never reordered. The registry resolves dependencies by
    position (``IndexedResolution.DepIndex``) and the injector applies them by
    position in the decorator's metadata list, so silently omitting a
    degenerate entry would shift every later dependency onto the wrong slot —
    a far worse outcome than publishing an edge that cannot resolve. Degenerate
    entries are therefore warned about and emitted as-is.
    """
    if cluster_strict is None:
        cluster_strict = cluster_strict_enabled()

    specs = []
    for index, dep_info in enumerate(dep_infos):
        if isinstance(dep_info, str):
            dep_info = {"capability": dep_info, "tags": []}
        elif not isinstance(dep_info, dict):
            logger.warning(
                f"Dependency at index {index} has unsupported type "
                f"{type(dep_info).__name__}; publishing an empty-capability edge "
                f"to keep dependency indices aligned. It will never resolve."
            )
            dep_info = {"capability": "", "tags": []}
        if not dep_info.get("capability"):
            logger.warning(
                f"Dependency at index {index} has an empty capability; it will "
                f"never resolve. Publishing it anyway so the indices of later "
                f"dependencies still line up with the injector."
            )
        specs.append(
            build_dependency_spec(core, dep_info, cluster_strict=cluster_strict)
        )
    return specs
