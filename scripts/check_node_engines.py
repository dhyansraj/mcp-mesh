#!/usr/bin/env python3
"""Every package that depends on the mesh TypeScript runtime must declare a
Node floor at least as high as the runtime's own (#1420).

The defect this exists to stop
------------------------------
`src/runtime/typescript/package.json` declares `engines: {node: ">=22.0.0"}`,
while 44 example and fixture packages that depend on `@mcpmesh/sdk` declared
`>=18` and 56 more declared nothing at all. That is not merely stale — it is
wrong in the direction that hides the failure. `npm install` succeeds on Node
18 or 20 because the example's *own* constraint is satisfied, and the
incompatibility surfaces later from runtime code, at a point that does not
name the example that caused it. The 56 with no `engines` field are the same
defect one notch quieter: npm cannot even warn.

Resetting those 100 files fixes the number. It does not fix the drift — the
next time the runtime floor moves, every one of them is wrong again and
nothing says so. The floor is mechanically derivable from a single file, so
this check derives it rather than restating it.

What counts as "depends on the runtime"
---------------------------------------
`@mcpmesh/sdk` and `@mcpmesh/core` — the two packages that carry the
TypeScript runtime. Keying on those two rather than on the `@mcpmesh/*` scope
matters: `npm/cli` optionally depends on `@mcpmesh/cli-{linux,darwin}-{x64,arm64}`,
which are prebuilt **Go** binaries. It never loads the TypeScript runtime, so
its `>=18` is an accurate claim about what it needs and must not be swept. A
scope-wide rule would have flagged it and needed an allowlist entry; naming
the two runtime packages makes it correct by construction instead.

The runtime packages themselves are not checked — they are the floor, not
consumers of it.

Usage
-----
    python3 scripts/check_node_engines.py           # report, exit 1 on failure
    python3 scripts/check_node_engines.py --list    # show every package's floor

Stdlib only, matching the scripts-test CI job, which installs nothing but
pytest.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

PROJECT_ROOT = pathlib.Path(__file__).parent.parent

# The single source of truth for the floor.
RUNTIME_MANIFEST = "src/runtime/typescript/package.json"

# Depending on either of these means loading the TypeScript runtime.
MESH_RUNTIME_PACKAGES = ("@mcpmesh/sdk", "@mcpmesh/core")

# These two ARE the runtime; they define the floor rather than consuming it.
RUNTIME_OWN_MANIFESTS = (
    RUNTIME_MANIFEST,
    "src/runtime/core/typescript/package.json",
)

DEPENDENCY_SECTIONS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
)

_FLOOR = re.compile(r"^\s*>=\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?\s*$")


def parse_floor(spec: str) -> tuple[int, int, int] | None:
    """`">=22.0.0"` / `">=18"` -> `(22, 0, 0)` / `(18, 0, 0)`.

    Deliberately narrow. A range this check cannot read (`^22`, `22.x`,
    `>=20 <23`) is reported as unreadable rather than guessed at: every
    package.json in this repo states a plain `>=` floor, and silently
    accepting a form whose minimum we inferred is how a check starts being
    wrong without being red.
    """
    m = _FLOOR.match(spec)
    if not m:
        return None
    major, minor, patch = m.groups()
    return (int(major), int(minor or 0), int(patch or 0))


def format_floor(floor: tuple[int, int, int]) -> str:
    return ">={}.{}.{}".format(*floor)


def tracked_package_json(root: pathlib.Path | None = None) -> list[str]:
    """Tracked `package.json` paths, vendored trees excluded."""
    root = root or PROJECT_ROOT
    out = subprocess.run(
        ["git", "ls-files", "*package.json"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(
        rel
        for rel in out.splitlines()
        if rel and "node_modules/" not in rel
    )


def runtime_floor(root: pathlib.Path | None = None) -> tuple[int, int, int]:
    root = root or PROJECT_ROOT
    data = json.loads((root / RUNTIME_MANIFEST).read_text())
    spec = (data.get("engines") or {}).get("node")
    if not spec:
        raise AssertionError(
            f"{RUNTIME_MANIFEST} declares no engines.node — this check derives "
            "the floor from it, so there is nothing to enforce."
        )
    floor = parse_floor(spec)
    if floor is None:
        raise AssertionError(
            f"{RUNTIME_MANIFEST} declares engines.node={spec!r}, which is not a "
            "plain `>=` floor. Teach parse_floor() about it before using it as "
            "the source of truth."
        )
    return floor


def depends_on_runtime(data: dict) -> bool:
    for section in DEPENDENCY_SECTIONS:
        for name in data.get(section) or {}:
            if name in MESH_RUNTIME_PACKAGES:
                return True
    return False


def violations(root: pathlib.Path | None = None) -> list[str]:
    """Packages that load the runtime but under-declare (or omit) their floor."""
    root = root or PROJECT_ROOT
    floor = runtime_floor(root)
    want = format_floor(floor)
    found: list[str] = []

    for rel in tracked_package_json(root):
        if rel in RUNTIME_OWN_MANIFESTS:
            continue
        try:
            data = json.loads((root / rel).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            found.append(f"{rel}: unreadable ({exc})")
            continue
        if not depends_on_runtime(data):
            continue

        spec = (data.get("engines") or {}).get("node")
        if spec is None:
            found.append(
                f"{rel}: depends on the mesh TS runtime but declares no "
                f"engines.node, so npm cannot warn at all — set {want!r}"
            )
            continue
        declared = parse_floor(spec)
        if declared is None:
            found.append(
                f"{rel}: engines.node={spec!r} is not a plain `>=` floor this "
                f"check can compare — set {want!r}"
            )
            continue
        if declared < floor:
            found.append(
                f"{rel}: engines.node={spec!r} is below the runtime's {want!r}; "
                "npm install succeeds and the incompatibility surfaces later "
                "from runtime code"
            )
    return found


def inventory(root: pathlib.Path | None = None) -> list[tuple[str, str, bool]]:
    """`(path, declared engines.node or '-', depends on runtime)` for each."""
    root = root or PROJECT_ROOT
    rows = []
    for rel in tracked_package_json(root):
        try:
            data = json.loads((root / rel).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        spec = (data.get("engines") or {}).get("node") or "-"
        rows.append((rel, spec, depends_on_runtime(data)))
    return rows


def main() -> int:
    floor = runtime_floor()
    want = format_floor(floor)
    print(f"Runtime floor ({RUNTIME_MANIFEST}): {want}")

    if "--list" in sys.argv:
        for rel, spec, dep in inventory():
            print(f"  {'RUNTIME-DEP' if dep else '           '}  {spec:12} {rel}")
        print()

    found = violations()
    if found:
        print(f"❌ {len(found)} package(s) under-declare the Node floor:")
        for v in found:
            print(f"     {v}")
        print(
            "\n   The correct value is derived from "
            f"{RUNTIME_MANIFEST}; it is never a judgement call."
        )
        return 1

    # `@mcpmesh/sdk` depends on `@mcpmesh/core`, so the runtime manifest reads
    # as a runtime dependent in the inventory. It is excluded from the checked
    # set, so it must be excluded from the count too, or the summary claims one
    # more package was verified than actually was.
    checked = sum(
        1 for rel, _, dep in inventory() if dep and rel not in RUNTIME_OWN_MANIFESTS
    )
    print(
        f"✅ all {checked} package(s) depending on "
        f"{'/'.join(MESH_RUNTIME_PACKAGES)} declare a floor of at least {want}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
