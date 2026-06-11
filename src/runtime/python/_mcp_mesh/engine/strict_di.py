"""
Opt-in strict dependency-injection diagnostics (``MCP_MESH_STRICT_DI``).

Python DI's parameter-selection rules are deliberately permissive (issue
#1196): ambiguous or skipped injections log a prescriptive WARNING and the
agent keeps running. Teams that want rigor can set ``MCP_MESH_STRICT_DI``
to a truthy value to promote exactly that ambiguity/skip class of warnings
to errors at decoration/startup time — the error text is byte-identical to
the warning text, so the fix instructions travel with the failure.

Injection SEMANTICS are untouched in both modes: dependencies pair with
parameters positionally by declaration order, never by name (pinned by
``test_multiple_deps_pair_by_declaration_order_not_name``). Strict mode
only changes warn-vs-raise for the diagnostics; informational warnings
(e.g. the single-untyped-parameter "injecting anyway" notice) never raise.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class StrictDIError(ValueError):
    """A DI ambiguity/skip diagnostic promoted to an error by strict mode.

    Subclasses :class:`ValueError` deliberately: ``ValueError`` is the
    exception class ``@mesh.tool`` re-raises at decoration time for
    signature-contract violations (see the multi-``MeshJob`` rejection in
    ``analyze_mesh_job_signature`` and the dedicated ``except ValueError``
    branch in ``mesh.decorators``). Subclassing it means strict-mode
    failures propagate through the decorator's graceful-degradation
    catch-all without needing every call site to know about strict mode.

    The message is always the same prescriptive text the permissive-mode
    warning would have logged.
    """


# Cached per-process resolution of MCP_MESH_STRICT_DI. Strict mode is a
# process-level posture, not a per-call toggle — resolve the env var once
# (mirrors the cached-global convention used elsewhere in the engine, e.g.
# ``_REPORT_PROGRESS_CONVENTION`` in dependency_injector.py).
_STRICT_DI_ENABLED: Optional[bool] = None


def is_strict_di_enabled() -> bool:
    """True when ``MCP_MESH_STRICT_DI`` resolves truthy. Cached per process.

    Default (unset / falsy) is permissive: DI parameter-selection
    diagnostics stay warnings and behavior is unchanged.
    """
    global _STRICT_DI_ENABLED
    if _STRICT_DI_ENABLED is None:
        from ..shared.config_resolver import ValidationRule, get_config_value

        _STRICT_DI_ENABLED = bool(
            get_config_value(
                "MCP_MESH_STRICT_DI",
                default=False,
                rule=ValidationRule.TRUTHY_RULE,
            )
        )
    return _STRICT_DI_ENABLED


def _reset_strict_di_cache() -> None:
    """Drop the cached env resolution (test support only)."""
    global _STRICT_DI_ENABLED
    _STRICT_DI_ENABLED = None


def pluralize(count: int, singular: str, plural: Optional[str] = None) -> str:
    """Render ``count`` + a correctly-inflected noun (``"1 dependency"``,
    ``"3 dependencies"``, ``"0 entries"``).

    Lives here because the DI diagnostic messages are this module's
    "single choke point" concern — every count rendered into a
    warn-or-raise message should route through this so the prescriptive
    text never reads ``"1 entries"``.
    """
    noun = singular if count == 1 else (plural if plural is not None else f"{singular}s")
    return f"{count} {noun}"


def warn_or_raise(log: logging.Logger, message: str) -> None:
    """Emit ``message`` as a warning, or raise :class:`StrictDIError`.

    Single choke point for the DI ambiguity/skip diagnostic class so the
    warning text and the strict-mode error text can never drift apart.
    Informational diagnostics must NOT route through here — they stay
    plain ``log.warning`` calls in both modes.
    """
    if is_strict_di_enabled():
        raise StrictDIError(message)
    log.warning(message)
