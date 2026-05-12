"""Eager media store initialization for fail-fast startup.

When ``MCP_MESH_MEDIA_STORAGE=s3`` is set explicitly, instantiating the store
here (rather than at first LLM call) surfaces three classes of misconfiguration
at agent boot:

- ``boto3`` missing -> ``ImportError`` with install hint
- ``MCP_MESH_MEDIA_STORAGE_BUCKET`` unset -> ``ValueError`` naming the env var
- (opt-in) AWS creds / bucket unreachable -> ``RuntimeError`` from head_bucket probe

For ``local`` (the default), construction is essentially free, so we always run
this step — it costs nothing and keeps the contract uniform.
"""

import os
from typing import Any

from ..shared import PipelineResult, PipelineStatus, PipelineStep


class MediaStoreValidationStep(PipelineStep):
    """Eagerly initialize the media store so config errors surface at startup."""

    def __init__(self):
        super().__init__(
            name="media-store-validation",
            required=False,
            description="Eagerly initialize media store to fail-fast on misconfiguration",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        result = PipelineResult(message="Media store validation completed")

        # Local import keeps pipeline import-time cheap (and avoids pulling
        # the media subsystem during pure-decorator unit tests).
        from ...media.media_store import get_media_store

        try:
            store = get_media_store()
            result.add_context("media_store_type", type(store).__name__)
            backend = os.getenv("MCP_MESH_MEDIA_STORAGE", "local")
            result.message = (
                f"Media store initialized: {type(store).__name__} (backend='{backend}')"
            )
            self.logger.info(
                "Media store initialized: %s (backend='%s')",
                type(store).__name__,
                backend,
            )
        except (ImportError, ValueError, RuntimeError) as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Media store initialization failed: {e}"
            result.add_error(str(e))
            self.logger.error(
                "Media store initialization failed: %s", e
            )

        return result
