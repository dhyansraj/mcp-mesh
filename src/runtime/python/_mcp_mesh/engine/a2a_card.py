"""A2A v1.0 AgentCard JSON generator (issue #903 Phase 1B).

Builds the JSON body returned from ``GET {path}/.well-known/agent.json`` for
each ``@mesh.a2a`` decorated function. The card shape follows the A2A v1.0
specification at https://a2a-protocol.org/latest/specification/.

Phase 1B emits one card per surface with one skill (per the design doc's
"Per-skill agent cards as default" decision). Multi-skill grouping is v2.

The card is intentionally minimal — we populate the fields the A2A v1.0 spec
requires plus the optional fields we have data for from the decorator
metadata. We deliberately leave optional fields empty rather than fabricate
values (e.g., ``provider``, ``documentationUrl``).
"""

from __future__ import annotations

from typing import Any, Optional


def build_agent_card(
    *,
    name: str,
    description: str | None,
    version: str,
    public_url: str | None,
    skill_id: str,
    skill_name: str,
    skill_description: str | None,
    input_modes: list[str],
    output_modes: list[str],
    tags: list[str],
    streaming: bool,
    bearer_auth: bool,
    underlying_tool_input_schema: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build an A2A v1.0 AgentCard dict.

    Args:
        name: Agent display name (typically the @mesh.agent name).
        description: Agent-level description (free-form).
        version: Agent version string (semver).
        public_url: Registry-stamped public FQDN for ``POST {path}``
            (the JSON-RPC tasks/* entry point). May be ``None`` when
            ``MCP_MESH_PUBLIC_URL_PREFIX`` is unset on the registry —
            in that case the card omits the ``url`` field so external
            clients fail loudly rather than silently follow an empty URL.
        skill_id: A2A skill identifier (kebab-case).
        skill_name: Human-readable skill name.
        skill_description: Skill-level description.
        input_modes: A2A inputModes (e.g. ``["application/json"]``).
        output_modes: A2A outputModes (e.g. ``["application/json"]``).
        tags: Skill tags surfaced on the card.
        streaming: ``True`` when the underlying mesh tool is
            ``task=True`` — flips ``capabilities.streaming``.
        bearer_auth: ``True`` when the surface declared
            ``auth="bearer"`` — affects ``authentication.schemes``.
        underlying_tool_input_schema: JSON Schema for the underlying
            mesh tool's input. When present, embedded as
            ``skills[0].metadata.input_schema`` so an A2A client can
            inspect the parameter shape without out-of-band knowledge.
            Optional in the A2A spec.

    Returns:
        A dict that serializes to the A2A v1.0 AgentCard JSON shape.
    """
    skill: dict[str, Any] = {
        "id": skill_id,
        "name": skill_name,
        "description": skill_description or skill_name,
        "tags": tags,
        "inputModes": input_modes,
        "outputModes": output_modes,
    }

    if underlying_tool_input_schema is not None:
        # The A2A v1.0 spec doesn't reserve a canonical "input schema" slot
        # on Skill; we expose it under a metadata bag so the card stays
        # spec-compliant while still carrying the shape downstream tooling
        # (LangGraph etc.) typically wants.
        skill["metadata"] = {"input_schema": underlying_tool_input_schema}

    card: dict[str, Any] = {
        "name": name,
        "description": description or name,
        "version": version,
        "capabilities": {
            "streaming": bool(streaming),
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": input_modes,
        "defaultOutputModes": output_modes,
        "skills": [skill],
    }

    if public_url:
        card["url"] = public_url

    if bearer_auth:
        # A2A v1.0 spec: authentication.schemes is a list of scheme names.
        # For bearer-token, the conventional value is "bearer".
        card["authentication"] = {"schemes": ["bearer"]}
    else:
        # A2A v1.0 has no "none" scheme — only real scheme names like
        # "bearer", "oauth2", etc. Emit an empty schemes list so clients
        # see "no schemes advertised" (i.e., unauthenticated) rather
        # than rejecting an unknown scheme name.
        card["authentication"] = {"schemes": []}

    return card
