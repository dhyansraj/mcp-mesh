"""
A2A server setup step (issue #903 Phase 1B).

Mirrors ``api_startup/api_server_setup.py`` for the A2A flow. Prepares
heartbeat config + service-registration metadata for a user-owned
FastAPI app that has declared ``@mesh.a2a`` / ``mesh.a2a.mount``
surfaces. This step does NOT create or modify the FastAPI app — it
only computes the registration shape the heartbeat task ships to the
registry on each round-trip.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from ...shared.config_resolver import ValidationRule, get_config_value
from ...shared.host_resolver import HostResolver
from ...shared.slug import slugify_service_name
from ..shared import PipelineResult, PipelineStatus, PipelineStep


class A2AServerSetupStep(PipelineStep):
    """
    Minimal A2A server setup for FastAPI integration.

    Mirrors ``APIServerSetupStep`` but always emits ``service_type="a2a"``
    and pre-seeds the heartbeat context with the ``a2a_surfaces`` array
    so the rust a2a-heartbeat AgentSpec builder has zero work to do.
    """

    def __init__(self):
        super().__init__(
            name="a2a-server-setup",
            required=True,
            description="Prepare binding config + service registration for A2A FastAPI app",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Setup A2A server configuration."""
        self.logger.debug("Setting up A2A server configuration...")

        result = PipelineResult(message="A2A server setup completed")

        try:
            fastapi_apps = context.get("fastapi_apps", {})
            a2a_surfaces: List[Dict[str, Any]] = context.get("a2a_surfaces", [])

            if not fastapi_apps:
                result.status = PipelineStatus.FAILED
                result.message = "No FastAPI applications found"
                result.add_error("Cannot setup A2A server without existing FastAPI app")
                self.logger.error(
                    "❌ No FastAPI applications found. A2A pipeline requires "
                    "an existing FastAPI app with @mesh.a2a / mesh.a2a.mount surfaces."
                )
                return result

            if not a2a_surfaces:
                result.status = PipelineStatus.FAILED
                result.message = "No A2A surfaces found"
                result.add_error(
                    "A2A pipeline executed without any registered @mesh.a2a surfaces"
                )
                self.logger.error(
                    "❌ A2A server setup requires at least one @mesh.a2a surface."
                )
                return result

            if len(fastapi_apps) > 1:
                self.logger.warning(
                    f"⚠️ Multiple FastAPI apps found ({len(fastapi_apps)}), "
                    "using the first one. Multi-app support coming in future."
                )

            primary_app_id = list(fastapi_apps.keys())[0]
            primary_app_info = fastapi_apps[primary_app_id]
            primary_app = primary_app_info["instance"]

            self.logger.info(
                f"🎯 Using FastAPI app: '{primary_app_info['title']}' as primary A2A host"
            )

            display_config = self._prepare_display_config()
            service_metadata = self._prepare_service_metadata(
                primary_app_info, a2a_surfaces, display_config
            )
            heartbeat_config = self._prepare_heartbeat_config(
                primary_app_info, display_config, service_metadata, a2a_surfaces
            )

            result.add_context("primary_fastapi_app", primary_app)
            result.add_context("fastapi_app", primary_app)
            result.add_context("a2a_display_config", display_config)
            result.add_context("display_config", display_config)
            result.add_context("a2a_service_metadata", service_metadata)
            result.add_context("service_type", "a2a")
            result.add_context("heartbeat_config", heartbeat_config)
            result.add_context("a2a_surfaces", a2a_surfaces)

            result.message = (
                f"A2A server config prepared for '{primary_app_info['title']}' "
                f"with {len(a2a_surfaces)} surface(s)"
            )

            self.logger.info(
                f"✅ A2A server setup: {primary_app_info['title']} ready "
                f"({len(a2a_surfaces)} surface(s); registry display: "
                f"{display_config['display_host']}:{display_config['display_port']})"
            )
            self.logger.info(
                f"🌐 A2A surfaces detected: {len(a2a_surfaces)} surface(s); "
                "service_type='a2a'"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"A2A server setup failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ A2A server setup failed: {e}")

        return result

    def _prepare_display_config(self) -> Dict[str, Any]:
        """
        Prepare display configuration for service registration.

        For A2A, the display host:port is what the registry advertises on
        the agent-card ``url`` (subject to MCP_MESH_PUBLIC_URL_PREFIX
        rewriting on the registry side). The user controls actual uvicorn
        binding separately.
        """
        external_host = HostResolver.get_external_host()

        display_port = get_config_value(
            "MCP_MESH_HTTP_PORT",
            default=8080,
            rule=ValidationRule.PORT_RULE,
        )

        display_host = get_config_value(
            "MCP_MESH_HTTP_HOST",
            default=external_host,
            rule=ValidationRule.STRING_RULE,
        )

        display_config = {
            "display_host": display_host,
            "display_port": display_port,
            "external_host": external_host,
        }

        self.logger.debug(
            f"📍 Display config: {display_host}:{display_port} "
            "(for registry display only - user controls actual uvicorn binding)"
        )

        return display_config

    def _prepare_service_metadata(
        self,
        app_info: Dict[str, Any],
        a2a_surfaces: List[Dict[str, Any]],
        display_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Prepare service registration metadata for the registry.

        Always emits ``service_type="a2a"``. The ``capabilities`` list is
        derived from the A2A surfaces (one entry per skill).
        """
        capabilities = []
        for surface in a2a_surfaces:
            capabilities.append(
                {
                    "name": surface.get("skill_id", "unknown"),
                    "type": "a2a_surface",
                    "path": surface.get("path"),
                }
            )

        service_metadata = {
            "service_name": app_info.get("title", "FastAPI A2A Service"),
            "service_version": app_info.get("version", "1.0.0"),
            "service_type": "a2a",
            "capabilities": capabilities,
            "total_surfaces": len(a2a_surfaces),
            "framework": "fastapi",
            "integration_method": "mesh_a2a_mount",
            "display_host": display_config["display_host"],
            "display_port": display_config["display_port"],
            "external_host": display_config["external_host"],
        }

        self.logger.debug(
            f"📋 Service metadata: {service_metadata['service_name']} "
            f"({len(capabilities)} A2A skill(s))"
        )

        return service_metadata

    def _prepare_heartbeat_config(
        self,
        app_info: Dict[str, Any],
        display_config: Dict[str, Any],
        service_metadata: Dict[str, Any],
        a2a_surfaces: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Prepare heartbeat configuration for A2A service.

        The surfaces array is pre-seeded into the heartbeat context so
        the rust a2a-heartbeat AgentSpec builder doesn't need to re-walk
        the DecoratorRegistry (the integrate path merges additional
        pipeline context on top of this seed).
        """
        service_id = self._get_or_generate_a2a_service_id(app_info)

        from ...shared.defaults import MeshDefaults

        heartbeat_interval = get_config_value(
            "MCP_MESH_HEALTH_INTERVAL",
            default=MeshDefaults.HEALTH_INTERVAL,
            rule=ValidationRule.NONZERO_RULE,
        )

        standalone_mode = get_config_value(
            "MCP_MESH_STANDALONE",
            default=False,
            rule=ValidationRule.TRUTHY_RULE,
        )

        seed_context: Dict[str, Any] = {"a2a_surfaces": list(a2a_surfaces)}

        heartbeat_config = {
            "service_id": service_id,
            "interval": heartbeat_interval,
            "standalone_mode": standalone_mode,
            "context": seed_context,
        }

        try:
            from ...engine.decorator_registry import DecoratorRegistry

            # Slugify the FastAPI app title so it matches the registry's
            # name validation (lowercase alphanumeric + hyphens only).
            # "Date A2A Agent" → "date-a2a-agent". Non-ASCII chars (e.g.
            # "Café A2A ☕") are stripped to hyphens so registry validation
            # doesn't reject the resulting name. Helper is shared with the
            # API pipeline + ``_generate_a2a_service_id`` to keep the four
            # call sites consistent.
            raw_title = app_info.get("title")
            slug_name = slugify_service_name(raw_title, "a2a-service")

            # Plumb the discovered host/port into agent_config so the
            # card endpoint's local-fallback URL builder can produce
            # `http://{host}:{port}{path}` (env-var-derived defaults
            # would otherwise miss the user's actual uvicorn port).
            update = {"agent_id": service_id, "name": slug_name}
            if display_config.get("display_host"):
                update["http_host"] = display_config["display_host"]
            if display_config.get("display_port"):
                update["http_port"] = display_config["display_port"]
            DecoratorRegistry.update_agent_config(update)

            self.logger.debug(
                f"🔧 Stored A2A service ID '{service_id}' (name='{slug_name}', from title='{raw_title}') in decorator registry"
            )
        except Exception as e:
            self.logger.warning(
                f"⚠️ Failed to store A2A service ID in decorator registry: {e}"
            )

        self.logger.info(
            f"💓 A2A heartbeat config created: service_id='{service_id}', "
            f"interval={heartbeat_interval}s, standalone={standalone_mode}"
        )

        return heartbeat_config

    def _generate_a2a_service_id(
        self, app_info: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate A2A service ID using the same priority logic as MCP/API agents.

        Priority order:
        1. ``MCP_MESH_AGENT_ID`` environment variable — pinned ID, used
           verbatim with no slug or UUID suffix. This is how operators
           opt into a stable, externally-managed identity (e.g. Helm
           chart parameter).
        2. ``MCP_MESH_A2A_NAME`` environment variable
        3. ``MCP_MESH_AGENT_NAME`` environment variable (fallback)
        4. FastAPI app title slug (stable across restarts — without this
           the default ``a2a-{uuid8}`` would create a fresh registry entry
           every restart, leaving stale records).
        5. Default to ``"a2a-{uuid8}"``.
        """
        # ``MCP_MESH_AGENT_ID`` is the pinned-ID escape hatch — when set
        # we honour it verbatim (no slug, no UUID suffix). Operators use
        # this when the registry identity is managed externally (Helm
        # values, Terraform, etc.) and must be stable across restarts.
        pinned_id = get_config_value(
            "MCP_MESH_AGENT_ID",
            default=None,
            rule=ValidationRule.STRING_RULE,
        )
        if pinned_id:
            self.logger.debug(
                f"Using pinned A2A service ID from MCP_MESH_AGENT_ID: '{pinned_id}'"
            )
            return pinned_id

        a2a_name = get_config_value(
            "MCP_MESH_A2A_NAME",
            default=None,
            rule=ValidationRule.STRING_RULE,
        )

        if not a2a_name:
            a2a_name = get_config_value(
                "MCP_MESH_AGENT_NAME",
                default=None,
                rule=ValidationRule.STRING_RULE,
            )

        # Fall back to the FastAPI app title for a stable identity across
        # restarts (the cached-config reuse logic at
        # ``_get_or_generate_a2a_service_id`` will then hit on subsequent
        # runs since the resulting service_id contains "a2a-" or "-a2a-").
        if not a2a_name and app_info and app_info.get("title"):
            a2a_name = app_info["title"]

        # Use the shared slug helper — the empty-fallback ("") is the
        # sentinel that triggers the "a2a-{uuid8}" branch below.
        cleaned_name = slugify_service_name(a2a_name, "")

        uuid_suffix = str(uuid.uuid4())[:8]

        if not cleaned_name:
            service_id = f"a2a-{uuid_suffix}"
        elif "a2a" in cleaned_name.lower():
            service_id = f"{cleaned_name}-{uuid_suffix}"
        else:
            service_id = f"{cleaned_name}-a2a-{uuid_suffix}"

        self.logger.debug(
            f"Generated A2A service ID: '{service_id}' from name source: '{a2a_name}'"
        )

        return service_id

    def _get_or_generate_a2a_service_id(
        self, app_info: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Get existing service ID from decorator registry or generate a new one.
        """
        try:
            from ...engine.decorator_registry import DecoratorRegistry

            current_config = DecoratorRegistry.get_resolved_agent_config()
            existing_id = current_config.get("agent_id", "")

            is_a2a_format = (
                existing_id.startswith("a2a-")
                or "-a2a-" in existing_id
            )

            if existing_id and is_a2a_format:
                self.logger.info(
                    f"🔄 Reusing existing A2A service ID: '{existing_id}'"
                )
                return existing_id

            new_id = self._generate_a2a_service_id(app_info)
            self.logger.info(
                f"🆕 Generated new A2A service ID: '{new_id}'"
            )
            return new_id

        except Exception as e:
            self.logger.warning(
                f"⚠️ Error checking existing service ID, generating new one: {e}"
            )
            return self._generate_a2a_service_id(app_info)
