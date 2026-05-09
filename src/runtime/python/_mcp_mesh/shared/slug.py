"""Shared slug helper for service / agent IDs.

Both ``api_server_setup`` and ``a2a_server_setup`` derive a kebab-case
service name from the FastAPI app title (or env-var override) so the
registry's name validation (lowercase alphanumeric + hyphens only)
accepts the result. The transformation is identical in both pipelines
and was previously inlined in four call sites — this module is the
single source of truth.
"""

from __future__ import annotations

import re

_NON_SLUG_CHAR_RE = re.compile(r"[^a-z0-9-]+")


def slugify_service_name(raw_name: str | None, fallback: str) -> str:
    """Return a registry-safe slug derived from ``raw_name``.

    Lowercases, converts spaces and underscores to hyphens, strips any
    remaining non ``[a-z0-9-]`` characters (including non-ASCII like
    emoji), collapses runs of hyphens, and falls back to ``fallback``
    when the result would otherwise be empty (e.g. all-emoji input).

    Args:
        raw_name: The candidate name (typically the FastAPI app title
            or an env-var override). ``None`` and empty strings yield
            ``fallback`` directly.
        fallback: The slug to return when ``raw_name`` is empty or
            slugifies to an empty string. Pipeline-specific defaults:
            ``"a2a-service"`` for the A2A pipeline, ``"api-service"``
            for the API pipeline.
    """
    if not raw_name:
        return fallback
    slug = raw_name.lower().replace(" ", "-").replace("_", "-")
    slug = _NON_SLUG_CHAR_RE.sub("-", slug)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or fallback
