"""
Dual-module tool registration detection (issue #1031).

When a Python mesh agent's entry script (e.g. ``main.py``) is launched as
``python main.py`` and a sibling module imports from it via
``from main import X``, Python evaluates ``main.py`` twice as two distinct
module objects — ``__main__`` (the entry) and ``main`` (the re-import). The
``@mesh.tool`` decorator fires once per module, registering the same tool
under two different fully-qualified function ids (``__main__.X:dep_0`` and
``main.X:dep_0``). Each registration carries independent DI state — only
one is wired to the running pipeline, so the other silently injects ``None``
for every dependency parameter when called from sibling code.

This module detects that pattern by scanning the DI dependency-mapping keys
and pairing entries whose suffix-after-the-first-dot is identical but whose
module prefix differs (specifically: one starts with ``__main__.``). The
caller emits a loud ERROR and aborts startup so the user sees the
misconfiguration before the agent starts serving traffic.
"""

from __future__ import annotations

from typing import Iterable


def detect_dual_module_registration(
    registry_keys: Iterable[str],
) -> list[tuple[str, str, str]]:
    """Find tools registered under both ``__main__.X`` and ``<module>.X``.

    Args:
        registry_keys: Iterable of DI dependency-mapping keys, each shaped
            ``"<module>.<qualname>:dep_<N>"`` (e.g.
            ``"__main__.dispatch_llm_participant:dep_0"``).

    Returns:
        List of ``(suffix, main_form_key, other_form_key)`` triples — one per
        collision pair. The ``suffix`` is everything after the first dot and
        is useful for human-readable error messages. Returns an empty list
        when no dual-module collisions are detected.

    The detection is intentionally conservative:

    - Only pairs where ONE side starts with ``__main__.`` AND the other does
      NOT count as collisions. Two unrelated modules that happen to define a
      function with the same bare name (e.g. ``pkg_a.foo`` and ``pkg_b.foo``)
      are not flagged — that's a different problem.
    - Package-qualified entries (e.g. ``pkg.main.foo:dep_0``) split on the
      first dot to ``pkg`` / ``main.foo:dep_0``, so the suffix grouping
      naturally avoids false-positives against a sibling ``__main__.foo:dep_0``
      (suffix ``foo:dep_0``) — they end up in different buckets.

    Note: the algorithm flags any pair ``__main__.<suffix>`` vs
    ``<single>.<suffix>`` where ``<single>`` is a top-level module name. In
    rare cases this can flag a genuine collision between an
    ``__main__``-defined tool and a same-named tool in a separate top-level
    module — that's a real ambiguity the user should resolve regardless of
    dual-import semantics, so the conservative behavior of flagging it is
    intentional.
    """
    by_suffix: dict[str, list[str]] = {}
    for key in registry_keys:
        if "." not in key:
            # Bare keys (no module prefix) can't form a dual-module pair.
            continue
        _module, suffix = key.split(".", 1)
        by_suffix.setdefault(suffix, []).append(key)

    collisions: list[tuple[str, str, str]] = []
    for suffix, keys in by_suffix.items():
        if len(keys) < 2:
            continue
        # Find the __main__-prefixed entry (if any) and pair it against
        # every non-__main__ sibling sharing the same suffix.
        main_form = next((k for k in keys if k.startswith("__main__.")), None)
        if main_form is None:
            continue
        for other in keys:
            if other is main_form:
                continue
            if other.startswith("__main__."):
                # Two __main__ entries with identical suffix shouldn't be
                # possible (the dict would just overwrite), but be defensive.
                continue
            collisions.append((suffix, main_form, other))

    return collisions
