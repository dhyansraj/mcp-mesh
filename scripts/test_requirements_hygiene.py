#!/usr/bin/env python3
"""Repo-wide hygiene checks over every tracked requirements file (#1404).

`examples/docker-examples/agents/base/requirements.txt` listed a bare
`asyncio`, which on PyPI is a distinct project from the stdlib module of the
same name. Nothing built that file — no Dockerfile copied it, no CI job read
it — so no check ever looked at what it declared, which is why the entry
survived. The file is gone; this module is what makes the *class* of defect
visible in a file that is only ever read by a human.

On the severity: measured, `pip install asyncio` on python:3.11-slim today
resolves to 4.0.0, which is metadata-only (a `dist-info` directory and
nothing else) and does not shadow anything. The pinned `asyncio==3.4.3` does
install a real `site-packages/asyncio/__init__.py`, but the stdlib directory
precedes `site-packages` on `sys.path`, so even that one loses on a default
layout. The entry was therefore junk rather than a live trap — but a
requirements line naming a stdlib module is never what the author meant, and
`PYTHONPATH` (which *does* precede the stdlib) is one env var away from
turning it back into one.

Stdlib only, matching the scripts-test job, which installs nothing but pytest.
"""

import os
import pathlib
import re
import sys

PROJECT_ROOT = pathlib.Path(__file__).parent.parent

# Vendored, generated and virtual-env trees carry third-party requirement
# files that are not ours to police.
_PRUNE = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "target",
    ".mypy_cache",
    ".pytest_cache",
    "site-packages",
}

_REQUIREMENTS_NAME = re.compile(r"^requirements[^/]*\.txt(\.tmpl)?$")


def requirement_files(root: pathlib.Path | None = None) -> list[pathlib.Path]:
    """Every requirements file in the working tree, vendored trees pruned."""
    root = root or PROJECT_ROOT
    found: list[pathlib.Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in _PRUNE and not d.startswith(".")
        ]
        for name in filenames:
            if _REQUIREMENTS_NAME.match(name):
                found.append(pathlib.Path(dirpath) / name)
    return sorted(found)


def requirement_names(path: pathlib.Path) -> list[tuple[int, str, str]]:
    """`(lineno, distribution name, raw line)` for each requirement declared.

    Comments, blank lines, pip flags (`-r`, `--index-url`) and templated lines
    are skipped. The name is normalised the way PEP 503 does, so `Foo_Bar` and
    `foo-bar` compare equal.
    """
    out: list[tuple[int, str, str]] = []
    for lineno, raw in enumerate(
        path.read_text(errors="replace").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if "{{" in line:  # scaffold template placeholder
            continue
        name = re.split(r"[<>=!~;\[\s]", line, maxsplit=1)[0].strip()
        if not name:
            continue
        out.append((lineno, name.lower().replace("-", "_").replace(".", "_"), raw))
    return out


def stdlib_shadowing(paths: list[pathlib.Path]) -> list[str]:
    """Requirement lines whose distribution name is also a stdlib module."""
    stdlib = set(sys.stdlib_module_names)
    hits: list[str] = []
    for path in paths:
        try:
            rel: pathlib.Path | str = path.relative_to(PROJECT_ROOT)
        except ValueError:  # a fixture outside the tree
            rel = path
        for lineno, name, raw in requirement_names(path):
            if name in stdlib:
                hits.append(f"{rel}:{lineno}: {raw.strip()!r} shadows stdlib {name!r}")
    return hits


def test_no_requirement_shadows_a_stdlib_module():
    paths = requirement_files()
    assert paths, "found no requirements files at all — the walker is broken"
    hits = stdlib_shadowing(paths)
    assert not hits, (
        f"{len(hits)} requirement line(s) name a stdlib module, so pip resolves "
        "an unrelated PyPI project of the same name:\n  " + "\n  ".join(hits)
    )


def test_shadow_check_bites(tmp_path):
    """A check only ever observed passing is indistinguishable from one that
    cannot fail. Feed it the exact line #1404 removed and it must go red."""
    bad = tmp_path / "requirements.txt"
    bad.write_text("fastapi>=0.135.0\n\n# Core Python async support\nasyncio\n")
    hits = stdlib_shadowing([bad])
    assert len(hits) == 1, hits
    assert "asyncio" in hits[0] and ":4:" in hits[0]

    # ...and stay quiet on the same file without that line.
    ok = tmp_path / "requirements-ok.txt"
    ok.write_text("fastapi>=0.135.0\nuvicorn>=0.24.0\n-r other.txt\n# asyncio\n")
    assert stdlib_shadowing([ok]) == []


def test_walker_prunes_vendored_trees(tmp_path):
    """node_modules / .venv hold third-party requirement files that would
    otherwise fail the stdlib check for reasons that are not ours to fix."""
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "requirements.txt").write_text("fastapi\n")
    for vendored in ("node_modules", ".venv", "__pycache__"):
        d = tmp_path / vendored / "pkg"
        d.mkdir(parents=True)
        (d / "requirements.txt").write_text("asyncio\n")

    found = requirement_files(tmp_path)
    assert [p.parent.name for p in found] == ["agent"], found


def test_the_orphan_requirements_file_is_gone():
    """#1404: `examples/docker-examples/agents/base/requirements.txt` was read
    by nothing — neither sibling Dockerfile copied it — so it was build
    metadata that only ever degraded. Re-adding it needs a consumer, and this
    assertion is where that conversation starts."""
    orphan = PROJECT_ROOT / "examples/docker-examples/agents/base/requirements.txt"
    assert not orphan.exists(), (
        f"{orphan.relative_to(PROJECT_ROOT)} is back. Nothing built it before; "
        "if something does now, wire that consumer up and delete this check."
    )


if __name__ == "__main__":
    import tempfile

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        if "tmp_path" in fn.__code__.co_varnames[: fn.__code__.co_argcount]:
            with tempfile.TemporaryDirectory() as d:
                fn(pathlib.Path(d))
        else:
            fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed")
