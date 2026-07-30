#!/usr/bin/env python3
"""Assert a version bump moved ONLY mcp-mesh versions in the two lockfiles.

Why this exists (#1407)
-----------------------
``scripts/bump_version.py`` used to tell operators to run
``cargo generate-lockfile`` after a bump. That command re-resolves the entire
Rust dependency graph from scratch, so following it turned a version bump into
an unreviewed dependency bump: v3.2.3 and v3.3.1 each shipped six third-party
crate moves this way, and v3.3.1's notes claimed runtime behavior was
"byte-for-byte identical" while its native module had been rebuilt against a
different ``napi``/``cc`` set.

Neither bump guard can see this. Both only inspect lines carrying the mesh
version, and the churn hides inside a ~450-file release diff.

The reminder is now ``cargo update --package mcp-mesh-core``, which locks one
package. This script is the assertion that makes an accidental re-resolution
fail loudly instead of riding along:

  * ``src/runtime/core/Cargo.lock`` — the only package whose version may move
    during a bump is ``mcp-mesh-core``. Any other crate that moves, appears or
    disappears is a graph re-resolution.
  * ``helm/mcp-mesh-core/Chart.lock`` — same rule for chart versions. Only
    ``digest`` and ``generated`` may change alongside them.

Both file comparisons are gated on the mesh version having actually moved: a
PR that deliberately bumps Rust dependencies (a fine thing to do, as its own
reviewed change) leaves ``mcp-mesh-core`` where it is and is not this script's
business.

A third check is ungated and needs no base ref: every chart dependency must
resolve from a ``file://`` path at an exact version. That is what makes
``helm dependency update`` structurally unable to pull an external chart
version the way ``cargo generate-lockfile`` pulls crates — it refreshes the
repo cache, but the six subcharts are local paths pinned exactly, so there is
nothing for it to re-resolve. The check pins that property rather than
trusting it to stay true.

Usage
-----
    python3 scripts/check_release_lockfiles.py              # vs HEAD (local)
    python3 scripts/check_release_lockfiles.py --base origin/main   # in CI

Stdlib only, so it runs anywhere the bump script does.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

CARGO_LOCK = "src/runtime/core/Cargo.lock"
CHART_LOCK = "helm/mcp-mesh-core/Chart.lock"
CHART_YAML = "helm/mcp-mesh-core/Chart.yaml"

# The one crate and the chart family a version bump is allowed to move.
CARGO_MESH_PACKAGE = "mcp-mesh-core"
_MESH_CHART = re.compile(r"^mcp-mesh(-|$)")


# ---------------------------------------------------------------------------
# Parsing (pure functions — the tests feed these strings directly)
# ---------------------------------------------------------------------------


def parse_cargo_lock(text: str) -> dict[str, list[str]]:
    """Map every ``[[package]]`` name to its sorted list of locked versions.

    A name can legitimately appear more than once (``syn 2.0.119`` and
    ``syn 3.0.3`` coexist today), so the value is a list, not a scalar —
    collapsing it would hide a major-version fan-out.

    ``name``/``version`` are read only at column 0 inside a package block; the
    ``dependencies = [...]`` array indents its entries, so there is no
    ambiguity.
    """
    packages: dict[str, list[str]] = {}
    name: str | None = None
    version: str | None = None
    in_package = False

    def flush() -> None:
        if in_package and name and version:
            packages.setdefault(name, []).append(version)

    for line in text.splitlines():
        if line.strip() == "[[package]]":
            flush()
            in_package, name, version = True, None, None
            continue
        if line.startswith("[") and line.strip() != "[[package]]":
            flush()
            in_package, name, version = False, None, None
            continue
        if not in_package:
            continue
        m = re.match(r'^name = "([^"]*)"', line)
        if m:
            name = m.group(1)
            continue
        m = re.match(r'^version = "([^"]*)"', line)
        if m:
            version = m.group(1)
    flush()

    return {k: sorted(v) for k, v in packages.items()}


def parse_chart_lock(text: str) -> dict[str, str]:
    """Map every ``Chart.lock`` dependency name to its locked version."""
    deps: dict[str, str] = {}
    name: str | None = None
    for line in text.splitlines():
        m = re.match(r"^- name:\s*(\S+)", line)
        if m:
            name = m.group(1)
            continue
        m = re.match(r"^\s+version:\s*(\S+)", line)
        if m and name:
            deps[name] = m.group(1).strip("\"'")
            name = None
    return deps


def parse_chart_dependencies(text: str) -> list[dict[str, str]]:
    """Read the ``dependencies:`` block of a ``Chart.yaml`` into dicts.

    Deliberately not PyYAML: this runs in the same stdlib-only environment as
    the bump script, and the block is a flat list of scalar keys.
    """
    deps: list[dict[str, str]] = []
    in_deps = False
    current: dict[str, str] | None = None
    for line in text.splitlines():
        if re.match(r"^dependencies:\s*(\[\s*\])?\s*$", line):
            in_deps = "[]" not in line
            continue
        if in_deps and re.match(r"^\S", line):
            break  # a new top-level key ends the block
        if not in_deps:
            continue
        m = re.match(r"^\s*-\s*(\w[\w.-]*):\s*(.*)$", line)
        if m:
            current = {m.group(1): m.group(2).strip().strip("\"'")}
            deps.append(current)
            continue
        m = re.match(r"^\s+(\w[\w.-]*):\s*(.*)$", line)
        if m and current is not None:
            current[m.group(1)] = m.group(2).strip().strip("\"'")
    return deps


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def cargo_lock_findings(before: str, after: str) -> tuple[bool, list[str]]:
    """``(mesh_version_moved, foreign_changes)`` for a Cargo.lock pair."""
    b, a = parse_cargo_lock(before), parse_cargo_lock(after)
    mesh_moved = b.get(CARGO_MESH_PACKAGE) != a.get(CARGO_MESH_PACKAGE)

    foreign: list[str] = []
    for name in sorted(set(b) | set(a)):
        if name == CARGO_MESH_PACKAGE:
            continue
        old, new = b.get(name), a.get(name)
        if old == new:
            continue
        if old is None:
            foreign.append(f"{name}: added at {', '.join(new or [])}")
        elif new is None:
            foreign.append(f"{name}: removed (was {', '.join(old)})")
        else:
            foreign.append(f"{name}: {', '.join(old)} -> {', '.join(new)}")
    return mesh_moved, foreign


def chart_lock_findings(before: str, after: str) -> tuple[bool, list[str]]:
    """``(mesh_version_moved, foreign_changes)`` for a Chart.lock pair."""
    b, a = parse_chart_lock(before), parse_chart_lock(after)
    mesh_moved = any(
        _MESH_CHART.match(n) and b.get(n) != a.get(n) for n in set(b) | set(a)
    )

    foreign: list[str] = []
    for name in sorted(set(b) | set(a)):
        if _MESH_CHART.match(name):
            continue
        old, new = b.get(name), a.get(name)
        if old == new:
            continue
        foreign.append(f"{name}: {old or '(absent)'} -> {new or '(absent)'}")
    return mesh_moved, foreign


_EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:[-+][\w.]+)?$")


def chart_dependency_violations(chart_yaml: str) -> list[str]:
    """Chart dependencies that helm could resolve to something we did not pin.

    Two ways that could happen, both absent today:
      * a ``repository:`` that is not a ``file://`` path — helm then queries a
        remote index and picks whatever it finds;
      * a version constraint that is a RANGE (``^3.3``, ``>=3.0.0``) rather
        than an exact version — helm then picks the newest match.
    """
    violations: list[str] = []
    for dep in parse_chart_dependencies(chart_yaml):
        name = dep.get("name", "<unnamed>")
        repo = dep.get("repository", "")
        version = dep.get("version", "")
        if not repo.startswith("file://"):
            violations.append(
                f"{name}: repository {repo!r} is not a file:// path, so "
                "'helm dependency update' resolves it from a remote index"
            )
        if not _EXACT_VERSION.match(version):
            violations.append(
                f"{name}: version {version!r} is a range, not an exact pin, so "
                "'helm dependency update' may select a different chart"
            )
    return violations


# ---------------------------------------------------------------------------
# git plumbing + CLI
# ---------------------------------------------------------------------------


class RefError(RuntimeError):
    """The base ref does not resolve, so no comparison can be made.

    This has to be distinct from "the file is not there". ``git show`` exits
    128 for both, so folding them together made an unfetched ``origin/main``,
    a ``HEAD^`` on a root commit or a typo read as a skip — and a skip is a
    PASS here. The gate would then report success having compared nothing,
    which is the same defect class it exists to catch.
    """


def _resolve_ref(ref: str) -> str:
    """Return the commit ``ref`` names, or raise ``RefError``."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        raise RefError(f"cannot run git to resolve {ref!r}: {exc}") from exc
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RefError(
            f"base ref {ref!r} does not resolve to a commit. In CI this usually "
            "means the branch was not fetched (checkout needs fetch-depth: 0); "
            "locally it means the ref is a typo or HEAD has no parent."
        )
    return proc.stdout.strip()


def _git_show(ref: str, path: str) -> str | None:
    """Read ``path`` at an already-resolved ``ref``; ``None`` = path absent."""
    try:
        proc = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        raise RefError(f"cannot run git to read {path} at {ref}: {exc}") from exc
    return proc.stdout if proc.returncode == 0 else None


def _worktree(path: str) -> str | None:
    f = PROJECT_ROOT / path
    return f.read_text() if f.exists() else None


def _check_pair(label: str, path: str, base: str, findings) -> tuple[bool, bool]:
    """Run one lockfile comparison. Returns ``(ok, ran)``.

    Raises ``RefError`` when ``base`` does not resolve: that is a broken check,
    not a skippable condition, and it must not be reported as a pass.
    """
    ref = _resolve_ref(base)
    before, after = _git_show(ref, path), _worktree(path)
    if before is None or after is None:
        print(f"⏭  {label}: cannot read {path} at {base} or in the worktree; skipped")
        return True, False

    mesh_moved, foreign = findings(before, after)
    if not mesh_moved:
        print(
            f"⏭  {label}: the mesh version did not move between {base} and the "
            "worktree, so this is not a release bump; skipped"
        )
        return True, False
    if foreign:
        print(f"❌ {label}: {len(foreign)} non-mesh version(s) moved alongside ours:")
        for f in foreign:
            print(f"     {f}")
        return False, True

    print(f"✅ {label}: the mesh version moved and nothing else did.")
    return True, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base",
        default="HEAD",
        help=(
            "git ref holding the pre-bump lockfiles. Defaults to HEAD, which "
            "is what an operator wants immediately after a bump; CI should "
            "pass the merge base (e.g. origin/main)."
        ),
    )
    args = parser.parse_args(argv)

    failed = False

    try:
        ok, _ = _check_pair("Cargo.lock", CARGO_LOCK, args.base, cargo_lock_findings)
        failed |= not ok
        if not ok:
            print(
                "   'cargo generate-lockfile' re-resolves the WHOLE graph. Restore "
                f"{CARGO_LOCK} and re-run:\n"
                "     (cd src/runtime/core && cargo update --package mcp-mesh-core)\n"
                "   If the third-party moves are deliberate, land them as their own "
                "reviewed PR with their own release-note line — not inside a bump."
            )

        ok, _ = _check_pair("Chart.lock", CHART_LOCK, args.base, chart_lock_findings)
        failed |= not ok
    except RefError as exc:
        print(f"❌ lockfile comparison could not run: {exc}")
        return 1

    chart_yaml = _worktree(CHART_YAML)
    if chart_yaml is None:
        print(f"⏭  Chart.yaml: {CHART_YAML} not found; skipped")
    else:
        violations = chart_dependency_violations(chart_yaml)
        if violations:
            failed = True
            print(
                f"❌ Chart.yaml: {len(violations)} dependency(ies) are no longer "
                "pinned to an exact local chart:"
            )
            for v in violations:
                print(f"     {v}")
            print(
                "   'helm dependency update' can now select a chart version we "
                "did not choose, which is the Cargo.lock defect in chart form."
            )
        else:
            print(
                "✅ Chart.yaml: every dependency is an exact-version file:// "
                "subchart, so 'helm dependency update' has nothing external to "
                "re-resolve."
            )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
