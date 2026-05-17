"""Unit tests for dual-module @mesh.tool registration detection (issue #1031).

When a Python agent script ``main.py`` is launched as ``python main.py`` and a
sibling module imports from it as ``from main import X``, Python evaluates the
script twice (once as ``__main__``, once as ``main``). The ``@mesh.tool``
decorator fires once per module, producing two DI registrations with
mismatched state. ``detect_dual_module_registration`` finds those pairs so
startup can abort with a clear error before the agent serves traffic.
"""

from __future__ import annotations

from _mcp_mesh.engine.dual_module_detection import detect_dual_module_registration


class TestDualModuleDetection:
    """Positive and negative cases for the suffix-grouping algorithm."""

    def test_detects_main_plus_module_collision(self):
        registry = [
            "__main__.dispatch_llm_participant:dep_0",
            "main.dispatch_llm_participant:dep_0",
        ]
        collisions = detect_dual_module_registration(registry)
        assert len(collisions) == 1
        suffix, main_key, other_key = collisions[0]
        assert suffix == "dispatch_llm_participant:dep_0"
        assert main_key == "__main__.dispatch_llm_participant:dep_0"
        assert other_key == "main.dispatch_llm_participant:dep_0"

    def test_clean_main_only_registry_no_collision(self):
        registry = ["__main__.foo:dep_0", "__main__.bar:dep_1"]
        assert detect_dual_module_registration(registry) == []

    def test_two_non_main_modules_with_same_suffix_no_collision(self):
        # False-positive guard: two unrelated modules happen to define a
        # function with the same bare name. Not a dual-module bug — that's
        # just normal Python — so we must NOT flag it.
        registry = [
            "pkg_a.foo:dep_0",
            "pkg_b.foo:dep_0",
        ]
        assert detect_dual_module_registration(registry) == []

    def test_package_layout_with_main_module_no_collision(self):
        # When a package has a submodule named ``main``, the registry key
        # is "pkg.main.foo:dep_0" — first-dot split gives module=pkg,
        # suffix="main.foo:dep_0". A bare __main__ entry has suffix
        # "foo:dep_0". Different buckets → no collision (this is the
        # supported `python -m pkg.main` layout).
        registry = [
            "pkg.main.foo:dep_0",
            "__main__.foo:dep_0",
        ]
        assert detect_dual_module_registration(registry) == []

    def test_empty_registry(self):
        assert detect_dual_module_registration([]) == []

    def test_bare_keys_without_module_prefix_ignored(self):
        # Defensive: keys with no dot can't form a dual-module pair.
        registry = ["nokeydot", "__main__.foo:dep_0"]
        assert detect_dual_module_registration(registry) == []

    def test_multiple_collisions_all_reported(self):
        registry = [
            "__main__.foo:dep_0",
            "main.foo:dep_0",
            "__main__.bar:dep_1",
            "main.bar:dep_1",
            "__main__.unique:dep_0",  # only in __main__ — fine
        ]
        collisions = detect_dual_module_registration(registry)
        suffixes = sorted(suffix for suffix, _, _ in collisions)
        assert suffixes == ["bar:dep_1", "foo:dep_0"]

    def test_main_paired_against_multiple_aliases(self):
        # If somehow the script is imported under multiple aliases, every
        # non-__main__ sibling should be reported against the __main__
        # entry (rare in practice but worth covering).
        registry = [
            "__main__.foo:dep_0",
            "main.foo:dep_0",
            "agent.foo:dep_0",
        ]
        collisions = detect_dual_module_registration(registry)
        others = sorted(other for _, _, other in collisions)
        assert others == ["agent.foo:dep_0", "main.foo:dep_0"]
        assert all(main == "__main__.foo:dep_0" for _, main, _ in collisions)
