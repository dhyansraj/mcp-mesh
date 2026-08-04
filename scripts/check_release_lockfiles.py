#!/usr/bin/env python3
"""Assert a version bump moved ONLY mcp-mesh versions in the lockfiles.

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
  * ``src/runtime/python/constraints.txt`` — the Python dependency lock added
    by #1454. Same rule, one degree stricter: mcp-mesh's own packages are not
    listed in it (the bump script owns those versions elsewhere), so a version
    bump may move NOTHING here at all.

All three comparisons are gated on the mesh version having actually moved: a
PR that deliberately bumps Rust or Python dependencies (a fine thing to do, as
its own reviewed change) leaves the mesh version where it is and is not this
script's business. Cargo and Chart read that signal out of the lockfile itself;
the Python lock has no mesh entry to read, so it takes the signal from
``version = "..."`` in ``src/runtime/python/pyproject.toml``.

Why Python has a lockfile at all (#1454)
----------------------------------------
Python was the only runtime without one, so ``pip install mcp-mesh==X.Y.Z``
resolved a different tree depending on when it ran. That drift shipped twice:
an unpinned FastMCP flipped a DNS-rebinding default on rebuild and returned 421
for every k8s Python provider (#1312), and a *minor* openai bump (2.14 -> 2.52)
added a required response field that broke CI while local envs stayed green
(#1453). Both were version drift, which is why the lock records versions and
not hashes: ``--generate-hashes`` output in a constraints file flips pip into
``--require-hashes`` mode for the whole command, and that mode cannot install
the ``pip install -e .`` that CI depends on. Supply-chain integrity is a real
but separate goal needing a separate install path.

A fourth check is ungated and needs no base ref: every chart dependency must
resolve from a ``file://`` path at an exact version. That is what makes
``helm dependency update`` structurally unable to pull an external chart
version the way ``cargo generate-lockfile`` pulls crates — it refreshes the
repo cache, but the six subcharts are local paths pinned exactly, so there is
nothing for it to re-resolve. The check pins that property rather than
trusting it to stay true.

A fifth is the same idea for the Python lock: every entry must be an exact
``==`` pin and none may carry an extra. A range makes the file stop locking
anything; an extra makes pip reject it outright ("Constraints cannot have
extras"), which would take the runtime image builds down with it.

A sixth closes the one manifest change that is otherwise silent. A lock pin
that CONFLICTS with the manifest fails the install on every PR, loudly; a
dependency ADDED to the manifest and never locked conflicts with nothing and
just installs at whatever pip picks. So every third-party requirement
``packaging/pypi/pyproject.toml`` declares must appear in the lock.

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
PY_CONSTRAINTS = "src/runtime/python/constraints.txt"
PY_PYPROJECT = "src/runtime/python/pyproject.toml"
# The manifest the lock is RESOLVED against — the one PyPI publishes. Its bounds
# are the tighter of the two on ten packages (rich<14.0.0 and friends), so a lock
# built from the source tree's copy can name a version the published package
# forbids. It did: rich 15.0.0 against a published rich<14.0.0, which made the
# runtime image unbuildable.
PYPI_PYPROJECT = "packaging/pypi/pyproject.toml"

# Optional-dependency groups the lock covers. The dev tooling is deliberately
# absent (never shipped, and locking it would churn the file on every ruff
# release); so are [anthropic-bedrock] and [kubernetes], which are opt-in and,
# in boto3's case, publish most weekdays.
LOCKED_EXTRAS = ("litellm",)

# The one crate and the chart family a version bump is allowed to move.
CARGO_MESH_PACKAGE = "mcp-mesh-core"
_MESH_CHART = re.compile(r"^mcp-mesh(-|$)")

# Nothing matches this in the lock today — mesh's own distributions are
# deliberately absent from it. It exists so that adding one later (an
# ``mcp-mesh-core==`` pin, say) does not turn every release into a red gate.
# PyPI normalizes ``_`` to ``-``, but the file is read as text, so both.
_MESH_PY = re.compile(r"^mcp[-_]mesh([-_]|$)")


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


_PY_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;#]+)\s*(;.*)?$")


def parse_python_constraints(text: str) -> dict[str, str]:
    """Map every pinned distribution in ``constraints.txt`` to its version.

    Only column-0 lines are pins — the same rule the Cargo parser uses, and for
    the same reason. pip-compile writes each pin flush left and indents its
    ``# via ...`` provenance block underneath, so reading an indented line would
    invent packages out of annotations.

    Names are normalized (PEP 503) because the file is compared against itself
    across two commits and a regenerate could legitimately change ``_`` to
    ``-``; that is not a version move and must not read as one.
    """
    pins: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        m = _PY_PIN.match(line)
        if m:
            pins[re.sub(r"[-_.]+", "-", m.group(1)).lower()] = m.group(2)
    return pins


def parse_project_version(text: str) -> str | None:
    """Read ``version`` from the ``[project]`` table of a pyproject.toml.

    Section-scoped rather than a bare regex over the file: ``version`` is a
    common key and ``[tool.*]`` tables further down are free to carry their own.
    Not tomllib, only so this module keeps working on the stdlib of whatever
    interpreter the bump script is run with.
    """
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped == "[project]"
            continue
        if not in_project:
            continue
        m = re.match(r'^version\s*=\s*["\']([^"\']+)["\']', stripped)
        if m:
            return m.group(1)
    return None


def _strip_toml_comment(line: str) -> str:
    """Drop a trailing ``#`` comment, ignoring ``#`` inside a DOUBLE-quoted string.

    Deliberately partial. One quoting state, toggled by ``"`` only, so:

      * TOML literal strings (``'...'``) are not recognised; a ``#`` inside one
        would truncate the line.
      * an escaped ``\\"`` toggles the state like a real delimiter, inverting
        the polarity for the rest of the line.

    Both are safe for the only caller, ``_toml_array_strings``, which reads
    flat arrays of PEP 508 requirement strings: the manifests write those with
    double quotes, and a requirement carries neither a ``#`` nor an escape.
    That is the same assumption ``_toml_array_strings`` makes when it extracts
    with ``"([^"]*)"`` — a single-quoted requirement is invisible to both, so
    they agree rather than disagreeing.

    The failure direction matters: a mis-parse drops a requirement from the
    array, and ``unlocked_declared_dependencies`` then under-reports — the
    guard goes quiet about a package it should have flagged. If a manifest ever
    adopts single-quoted or escape-carrying requirements, move to ``tomllib``
    rather than growing this; do not let it keep guessing.
    """
    in_string = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_string = not in_string
        elif ch == "#" and not in_string:
            return line[:i]
    return line


def _toml_array_strings(text: str, section: str, key: str) -> list[str]:
    """Every quoted string in the ``key = [...]`` array of ``section``.

    Enough TOML for two flat arrays of requirement strings, and no more. Two
    things stop it being a one-line regex, and both are live in the real
    manifests:

      * ~40 lines of ``#`` provenance commentary sit INSIDE the dependencies
        array and quote package names in prose.
      * a requirement may carry an extra — ``anthropic[bedrock]>=0.77,<1``,
        ``bandit[toml]>=1.7.0``, ``mcp-mesh[litellm]``. The ``]`` in those is
        not the end of the array, so the terminator has to be looked for
        OUTSIDE the quoted strings. Reading it naively truncated the base
        dependency list at ``anthropic`` and silently under-reported what the
        lock has to cover, which is the opposite of what this check is for.

    Double quotes only, both here and in ``_strip_toml_comment``: see that
    docstring for what the shared assumption does and does not cover.
    """
    out: list[str] = []
    in_section = False
    collecting = False
    for raw in text.splitlines():
        line = _strip_toml_comment(raw).strip()
        if not collecting:
            if line.startswith("["):
                in_section = line == section
                continue
            if not in_section:
                continue
            m = re.match(rf"^{re.escape(key)}\s*=\s*\[(.*)$", line)
            if not m:
                continue
            collecting, line = True, m.group(1)
        out.extend(re.findall(r'"([^"]*)"', line))
        if "]" in re.sub(r'"[^"]*"', "", line):
            collecting = False
    return out


def parse_declared_dependencies(text: str, extras: tuple[str, ...] = ()) -> set[str]:
    """Normalized names of the DIRECT requirements a pyproject declares.

    Only the names — the version specifiers are the manifest's business, not the
    lock's. Extras on a requirement (``anthropic[bedrock]``) are stripped: the
    lock records distributions, and a distribution is the same one whether or
    not an extra was requested.
    """
    raw = _toml_array_strings(text, "[project]", "dependencies")
    for extra in extras:
        raw += _toml_array_strings(text, "[project.optional-dependencies]", extra)

    names: set[str] = set()
    for req in raw:
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", req.strip())
        if m:
            names.add(re.sub(r"[-_.]+", "-", m.group(1)).lower())
    return names


def unlocked_declared_dependencies(pyproject: str, constraints: str) -> list[str]:
    """Direct requirements the manifest declares that the lock does not pin.

    The gap this closes: adding a dependency to the manifest without
    regenerating the lock does not conflict with anything, so nothing complains
    — the new package simply installs at whatever version pip likes, in CI and
    in the images, which is the state this whole file exists to end. A version
    that CONFLICTS with the lock is already loud (pip fails the install on every
    PR); a version that is merely absent from it is silent.

    mcp-mesh's own distributions are exempt: they are deliberately excluded from
    the lock so that a release bump never has to touch it.
    """
    declared = parse_declared_dependencies(pyproject, LOCKED_EXTRAS)
    locked = parse_python_constraints(constraints)
    return sorted(
        name
        for name in declared
        if name not in locked and not _MESH_PY.match(name)
    )


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


def python_constraints_findings(
    before: str, after: str, mesh_moved: bool
) -> tuple[bool, list[str]]:
    """``(mesh_version_moved, foreign_changes)`` for a constraints.txt pair.

    ``mesh_moved`` is passed in rather than derived, because unlike Cargo.lock
    and Chart.lock this file contains no mcp-mesh entry to read it from. The
    caller takes it from ``src/runtime/python/pyproject.toml``.
    """
    b, a = parse_python_constraints(before), parse_python_constraints(after)

    foreign: list[str] = []
    for name in sorted(set(b) | set(a)):
        if _MESH_PY.match(name):
            continue
        old, new = b.get(name), a.get(name)
        if old == new:
            continue
        if old is None:
            foreign.append(f"{name}: added at {new}")
        elif new is None:
            foreign.append(f"{name}: removed (was {old})")
        else:
            foreign.append(f"{name}: {old} -> {new}")
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


def python_constraints_violations(text: str) -> list[str]:
    """Lines that stop ``constraints.txt`` from being a lock, or break pip.

    Ungated and base-ref-free, the way ``chart_dependency_violations`` is. Two
    failure modes, both silent until something much later goes wrong:

      * a line that is not an exact ``==`` pin (a ``>=`` range, an ``-r``
        include, a URL). pip accepts a range in a constraints file perfectly
        happily and then resolves whatever it likes inside it, so the file goes
        on existing while locking nothing.
      * an extra (``google-auth[requests]==2.56.2``). pip does NOT accept this
        — it hard-errors "Constraints cannot have extras" — and pip-compile
        emits five such lines the moment ``--strip-extras`` is dropped from the
        generator. That would fail both runtime image builds and the CI install
        at once, so it is worth catching in the diff that introduces it.
    """
    violations: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        if _PY_PIN.match(line):
            continue
        detail = (
            "carries an extra, which pip rejects in a constraints file"
            if re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*\[", line)
            else "is not an exact '==' pin"
        )
        violations.append(f"line {lineno}: {line.strip()!r} {detail}")
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


def _python_mesh_version_moved(base: str) -> bool:
    """Did this change bump the Python package's own version?

    The Cargo and Chart comparisons read that signal out of the lockfile they
    are checking. ``constraints.txt`` holds no mcp-mesh entry, so the signal has
    to come from the manifest beside it. Every failure here raises rather than
    returning ``False``: ``False`` means "not a release bump", which is a SKIP,
    which is a PASS — the exact shape of the defect ``RefError`` was introduced
    to close for the base ref.
    """
    ref = _resolve_ref(base)
    before, after = _git_show(ref, PY_PYPROJECT), _worktree(PY_PYPROJECT)
    if before is None or after is None:
        missing = "the base ref" if before is None else "the worktree"
        raise RefError(
            f"{PY_CONSTRAINTS} exists on both sides but {PY_PYPROJECT} could "
            f"not be read at {missing}, so whether this is a release bump "
            "cannot be determined. A comparison that did not happen must not "
            "be reported as a pass."
        )
    b, a = parse_project_version(before), parse_project_version(after)
    if b is None or a is None:
        missing = "the base ref" if b is None else "the worktree"
        raise RefError(
            f"{PY_PYPROJECT} has no [project] version at {missing}, so whether "
            "this is a release bump cannot be determined."
        )
    return b != a


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

        ok, _ = _check_pair(
            "constraints.txt",
            PY_CONSTRAINTS,
            args.base,
            lambda b, a: python_constraints_findings(
                b, a, _python_mesh_version_moved(args.base)
            ),
        )
        failed |= not ok
        if not ok:
            print(
                "   'scripts/lock_python_deps.sh --upgrade' re-resolves the "
                "WHOLE Python graph — it is this file's 'cargo "
                f"generate-lockfile'. Restore {PY_CONSTRAINTS} and, if a "
                "manifest change genuinely forced a move, re-run it WITHOUT "
                "--upgrade:\n"
                "     scripts/lock_python_deps.sh\n"
                "   If the third-party moves are deliberate, land them as their "
                "own reviewed PR with CI green against the new set — not inside "
                "a bump. That is how #1312 (a FastMCP default-flip) and #1453 "
                "(an openai minor adding a required field) reached us."
            )
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

    constraints = _worktree(PY_CONSTRAINTS)
    if constraints is None:
        print(f"⏭  constraints.txt: {PY_CONSTRAINTS} not found; skipped")
    else:
        violations = python_constraints_violations(constraints)
        if violations:
            failed = True
            print(
                f"❌ constraints.txt: {len(violations)} line(s) are not exact "
                "pins pip can use as constraints:"
            )
            for v in violations:
                print(f"     {v}")
            print(
                "   A range locks nothing; an extra makes pip reject the file "
                "outright ('Constraints cannot have extras') and takes both "
                "runtime image builds down with it. Regenerate with "
                "scripts/lock_python_deps.sh rather than editing by hand."
            )
        else:
            pins = len(parse_python_constraints(constraints))
            print(
                f"✅ constraints.txt: all {pins} entries are exact pins with no "
                "extras, so pip can apply the file as written."
            )

        published = _worktree(PYPI_PYPROJECT)
        if published is None:
            print(f"⏭  {PYPI_PYPROJECT} not found; coverage check skipped")
        else:
            unlocked = unlocked_declared_dependencies(published, constraints)
            if unlocked:
                failed = True
                print(
                    f"❌ constraints.txt: {len(unlocked)} declared "
                    f"dependency(ies) of {PYPI_PYPROJECT} are not in the lock:"
                )
                for name in unlocked:
                    print(f"     {name}")
                print(
                    "   A dependency added without regenerating the lock does "
                    "not conflict with anything — it just installs whatever pip "
                    "picks, in CI and in the images. Run "
                    "scripts/lock_python_deps.sh."
                )
            else:
                declared = sum(
                    1
                    for n in parse_declared_dependencies(published, LOCKED_EXTRAS)
                    if not _MESH_PY.match(n)
                )
                print(
                    f"✅ constraints.txt: all {declared} third-party "
                    f"dependencies {PYPI_PYPROJECT} declares are pinned by the "
                    "lock."
                )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
