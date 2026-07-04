#!/usr/bin/env python3
"""Lightweight checks for scripts/bump_version.py's coverage-guard regexes.

Run directly (`python scripts/test_bump_version.py`) or via pytest. These
exercise `_guard_patterns` against representative lines so a future edit that
breaks mesh-shaped detection (like the @mcpmesh package.json form that the
first cut of the guard silently missed) fails loudly.
"""

import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "bump_version", pathlib.Path(__file__).with_name("bump_version.py")
)
bv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bv)


def _matches(old: str, line: str) -> bool:
    return any(p.search(line) for p in bv._guard_patterns(old))


def test_mcpmesh_package_json_forms():
    old = "2.8.0"
    # The form the first guard cut missed: version sits after `": "`, not
    # immediately after the package-name quote.
    assert _matches(old, '    "@mcpmesh/sdk": "^2.8.0"')       # caret, spaced
    assert _matches(old, '    "@mcpmesh/core": "2.8.0"')       # no caret
    assert _matches(old, '"@mcpmesh/sdk":"^2.8.0"')            # unspaced
    assert _matches(old, "npm install @mcpmesh/sdk@^2.8.0")    # npm shorthand


def test_other_mesh_contexts():
    old = "2.8.0"
    assert _matches(old, "FROM mcpmesh/python-runtime:2.8.0")
    assert _matches(old, "        <mcp-mesh.version>2.8.0</mcp-mesh.version>")
    assert _matches(old, "RUN pip install mcp-mesh>=2.8.0")
    assert _matches(old, '  tag: "2.8.0"')
    assert _matches(old, '  tag: "2.8"')  # minor-tag form


def test_non_mesh_lines_ignored():
    old = "2.8.0"
    assert not _matches(old, '        "node": ">=12.8.0"')      # engines range
    assert not _matches(old, 'version = "2.8.0"  # crate')      # third-party
    assert not _matches(old, "FROM mcpmesh/python-runtime:2.8.01")  # boundary


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed")
