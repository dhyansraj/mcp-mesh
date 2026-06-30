"""Shared wire-translation helpers for the native vendor adapters.

The three native adapters (anthropic_native, openai_native, gemini_native)
each translate caller-shape kwargs into their vendor SDK's actual call
signature. A few translations are near-identical across all three — this
module is the single source of truth for those.

Kept intentionally narrow: only translations that the WARN-once dedupe is
caller-supplied (each adapter owns its own dedupe state). Pure helpers
otherwise — no module-level state here.
"""

from __future__ import annotations

import logging
from typing import Any, Callable


def warn_unsupported_kwarg_once(
    dedupe_set: set[str],
    *,
    kwarg: str,
    adapter_label: str,
    sdk_call_label: str,
    logger: logging.Logger,
) -> None:
    """Log a WARNing for a dropped kwarg, deduplicating per-process via the
    caller-supplied set.

    Each adapter owns its own ``dedupe_set`` so dedupe is per-vendor — a
    LiteLLM-only kwarg dropped on the Anthropic path won't suppress the
    WARN if it later shows up on the OpenAI path (different translation
    surface, different signal).

    ``adapter_label`` is the human-readable vendor name ("Anthropic",
    "OpenAI", "Gemini"); ``sdk_call_label`` is the qualified SDK method
    referenced in the message body so reviewers can grep from the log line
    back to the dropping site.
    """
    if kwarg in dedupe_set:
        return
    dedupe_set.add(kwarg)
    logger.warning(
        "Native %s adapter dropping unsupported kwarg: '%s' "
        "(LiteLLM-only — not forwarded to %s)",
        adapter_label,
        kwarg,
        sdk_call_label,
    )


def reset_unsupported_kwargs_dedupe(dedupe_set: set[str]) -> None:
    """Clear the caller-supplied dedupe set so a re-run sees a fresh state.

    Test hook — NOT for production use. The adapters expose thin module-
    level wrappers (``_reset_unsupported_kwargs_dedupe``) that call this
    with their own module-level dedupe set.
    """
    dedupe_set.clear()


def restricts_sampling_params(model: str | None) -> bool:
    """Whether an OpenAI model restricts ``temperature``/``top_p`` to their
    default value (rejecting any explicit setting with HTTP 400).

    OpenAI o-series reasoning models (o1/o3/o4) and the gpt-5 family (except
    gpt-5-chat) accept ONLY the default sampling params. Verified against the
    live API:

      * REJECT: gpt-5, gpt-5-mini, gpt-5-nano, o1, o3-mini, o4-mini
      * ACCEPT: gpt-4o, gpt-4.1, gpt-5-chat-latest

    Accepts a bare or ``vendor/``-qualified model string (e.g.
    ``openai/o3-mini``). Returns ``True`` when ``temperature``/``top_p`` should
    be omitted. Mirrors the Java ``OpenAiHandler.restrictsSamplingParams``.
    """
    if not model:
        return False
    m = model.lower()
    if "/" in m:
        m = m.split("/", 1)[1]  # strip vendor prefix e.g. "openai/o3-mini"
    if m in ("o1", "o3", "o4") or m.startswith(("o1-", "o3-", "o4-")):
        return True
    if m.startswith("gpt-5") and not m.startswith("gpt-5-chat"):
        return True
    return False


def resolve_request_timeout(
    request_params: dict[str, Any],
    *,
    adapter_label: str,
    logger: logging.Logger,
    seconds_to_ms: bool = False,
) -> int | float | None:
    """Resolve caller's ``timeout`` / ``request_timeout`` to a single value.

    ``helpers._run_response_format_retry`` sets ``request_timeout=<fallback>``
    on the fallback retry to bound a slow API; caller code may pass
    ``timeout=`` directly. Both surface as kwargs the adapter must collapse
    into the vendor SDK's actual kwarg.

    Precedence: caller-supplied ``timeout`` wins over ``request_timeout``
    when both are present. The DEBUG log surfaces the actual decision so
    --debug runs can tell "translation never ran" from "caller's timeout
    won" (otherwise indistinguishable).

    With ``seconds_to_ms=True`` the resolved value is multiplied by 1000
    and coerced to ``int`` — Google's ``HttpOptions.timeout`` is documented
    as ``Optional[int]`` in milliseconds. WARN is logged (caller-observable)
    if the value cannot be coerced.

    Returns ``None`` when neither key is set or when ``seconds_to_ms``
    coercion fails. The adapter assigns the return value to its native
    shape (or skips entirely when ``None``).
    """
    timeout_value = request_params.pop("timeout", None)
    request_timeout = request_params.pop("request_timeout", None)

    # Precedence: caller's ``timeout`` wins.
    if timeout_value is not None:
        if request_timeout is not None:
            logger.debug(
                "%s: dropped request_timeout=%ss "
                "(caller-supplied timeout=%ss wins)",
                adapter_label,
                request_timeout,
                timeout_value,
            )
        chosen = timeout_value
    elif request_timeout is not None:
        logger.debug(
            "%s: translated request_timeout=%ss → vendor SDK timeout",
            adapter_label,
            request_timeout,
        )
        chosen = request_timeout
    else:
        return None

    if seconds_to_ms:
        try:
            return int(float(chosen) * 1000)
        except (TypeError, ValueError, OverflowError):
            logger.warning(
                "%s: cannot coerce timeout=%r to int; skipping per-call "
                "timeout override (HttpOptions.timeout requires "
                "Optional[int])",
                adapter_label,
                chosen,
            )
            return None

    return chosen


def make_is_available(
    import_name: str,
) -> tuple[Callable[[], bool], Callable[[], None]]:
    """Build the ``(is_available, reset)`` pair for a native adapter.

    Each adapter has a structurally-identical ``is_available()`` that probes
    whether its vendor SDK is importable, caching the result after the first
    probe — SDK presence does not change at runtime and the
    import-then-immediately-discard pattern was needless overhead on the
    dispatch-decision hot path.

    The cache lives in a closure cell here (one per adapter), so each
    adapter's pair is independent. ``reset`` is a test hook — the adapters
    expose it module-level as ``_reset_is_available_cache``.

    ``import_name`` is the importable module path. ``__import__`` is used
    (not ``importlib.import_module``) so the probe issues exactly the same
    ``__import__(import_name)`` a bare ``import`` statement would — the
    adapters' tests patch ``builtins.__import__`` and count those calls,
    and ``importlib.import_module`` would skip the call entirely when the
    module is already cached in ``sys.modules``.
    """
    cache: dict[str, bool] = {}

    def is_available() -> bool:
        cached = cache.get("value")
        if cached is not None:
            return cached
        try:
            __import__(import_name)
        except ImportError:
            cache["value"] = False
            return False
        cache["value"] = True
        return True

    def reset() -> None:
        """For tests — reset the cached availability probe. NOT for production."""
        cache.pop("value", None)

    return is_available, reset


def make_fallback_logger(
    extra_label: str,
    logger: logging.Logger,
    *,
    module_globals: dict[str, Any],
    flag_name: str = "_logged_fallback_once",
) -> tuple[Callable[[], None], Callable[[], bool], Callable[[], None]]:
    """Build the ``(log_fallback_once, is_fallback_logged, reset)`` trio.

    Each adapter emits a one-time INFO nudge ("Install `mcp-mesh[<extra>]`
    ...") when native dispatch was attempted but the vendor SDK is not
    importable. The trio dedupes that to once per process.

    State is the module-level ``flag_name`` attribute (default
    ``_logged_fallback_once``) read/written through ``module_globals`` — the
    adapters' tests ``monkeypatch.setattr(module, "_logged_fallback_once",
    ...)`` and expect ``is_fallback_logged()`` to reflect it, which only
    works if the flag stays a real module attribute (a closure cell would
    not be visible to the monkeypatch). Pass ``globals()`` from the adapter.

    ``extra_label`` is the pip extra ("anthropic" / "openai" / "gemini")
    interpolated into the install hint.
    """

    def log_fallback_once() -> None:
        if module_globals.get(flag_name):
            return
        module_globals[flag_name] = True
        logger.info(
            "Install `mcp-mesh[%s]` for native SDK with full feature "
            "support — falling back to LiteLLM",
            extra_label,
        )

    def is_fallback_logged() -> bool:
        return bool(module_globals.get(flag_name))

    def reset() -> None:
        """For tests — clear the one-time fallback-log flag. NOT for production."""
        module_globals[flag_name] = False

    return log_fallback_once, is_fallback_logged, reset
