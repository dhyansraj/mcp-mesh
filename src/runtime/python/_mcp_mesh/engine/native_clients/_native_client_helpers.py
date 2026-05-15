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
from typing import Any


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
