#!/usr/bin/env python3
"""Checks for scripts/check_node_engines.py (#1420).

The fixtures build throwaway git repos rather than reusing the real tree, so
the failure cases prove the check can actually go red instead of asserting
that the tree happens to be clean today. Every fixture version (`>=8`, `>=99`)
appears nowhere in the repo.
"""

import importlib.util
import json
import pathlib
import subprocess

_spec = importlib.util.spec_from_file_location(
    "check_node_engines",
    pathlib.Path(__file__).with_name("check_node_engines.py"),
)
cne = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cne)

PROJECT_ROOT = pathlib.Path(__file__).parent.parent

SCAFFOLD_TEMPLATES = sorted(
    (PROJECT_ROOT / "cmd/meshctl/templates/typescript").glob("*/package.json.tmpl")
)


def _repo(tmp_path: pathlib.Path, files: dict[str, dict]) -> pathlib.Path:
    """A throwaway git repo containing the given package.json files."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for rel, data in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2) + "\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _runtime(floor: str = ">=22.0.0") -> dict:
    return {"name": "@mcpmesh/sdk", "engines": {"node": floor}}


# --------------------------------------------------------------------------
# The floor is derived, never restated
# --------------------------------------------------------------------------


def test_floor_comes_from_the_runtime_manifest():
    declared = json.loads((PROJECT_ROOT / cne.RUNTIME_MANIFEST).read_text())
    assert cne.format_floor(cne.runtime_floor()) == declared["engines"]["node"]


def test_parse_floor_reads_both_spellings():
    assert cne.parse_floor(">=22.0.0") == (22, 0, 0)
    assert cne.parse_floor(">=18") == (18, 0, 0)
    assert cne.parse_floor(">= 20.1") == (20, 1, 0)


def test_parse_floor_refuses_ranges_it_would_have_to_guess_at():
    """Reporting an unreadable range beats inferring a minimum from it: a
    wrong inference is a check that is quietly wrong rather than red."""
    for spec in ("^22", "22.x", ">=20 <23", "*", ""):
        assert cne.parse_floor(spec) is None, spec


# --------------------------------------------------------------------------
# The tree
# --------------------------------------------------------------------------


def test_tree_has_no_under_declared_package():
    found = cne.violations()
    assert not found, "\n  ".join(["under-declared packages:"] + found)


def test_the_check_actually_covers_something():
    """A rule that matches no package passes for the wrong reason."""
    covered = [
        rel
        for rel, _, dep in cne.inventory()
        if dep and rel not in cne.RUNTIME_OWN_MANIFESTS
    ]
    assert len(covered) > 50, covered
    # The runtime manifest itself depends on @mcpmesh/core, so it reads as a
    # dependent; it must not be counted among the packages verified.
    assert cne.RUNTIME_MANIFEST not in covered


def test_scaffold_templates_emit_the_derived_floor():
    """The floor lives in two places by necessity: the runtime manifest and
    the five scaffold templates, which are what a newly generated agent gets.
    The templates were already right when #1420 was filed — only pre-existing
    examples had drifted — so this is here to keep the *next* runtime bump
    from splitting them apart silently."""
    want = cne.format_floor(cne.runtime_floor())
    assert SCAFFOLD_TEMPLATES, "no typescript scaffold templates found"
    bad = {}
    for tmpl in SCAFFOLD_TEMPLATES:
        # Go template syntax makes these invalid JSON; read the field directly.
        text = tmpl.read_text()
        marker = '"node": "'
        i = text.find(marker)
        got = text[i + len(marker) : text.find('"', i + len(marker))] if i >= 0 else None
        if got != want:
            bad[str(tmpl.relative_to(PROJECT_ROOT))] = got
    assert not bad, f"scaffold templates disagree with the runtime floor {want}: {bad}"


# --------------------------------------------------------------------------
# The check goes red — each failure mode separately
# --------------------------------------------------------------------------


def test_a_floor_below_the_runtime_is_flagged(tmp_path):
    root = _repo(
        tmp_path,
        {
            cne.RUNTIME_MANIFEST: _runtime(),
            "examples/agent-ts/package.json": {
                "name": "agent-ts",
                "engines": {"node": ">=8"},
                "dependencies": {"@mcpmesh/sdk": "^3.3.2"},
            },
        },
    )
    found = cne.violations(root)
    assert len(found) == 1, found
    assert "examples/agent-ts/package.json" in found[0]
    assert "'>=8' is below" in found[0]


def test_a_missing_engines_field_is_flagged(tmp_path):
    root = _repo(
        tmp_path,
        {
            cne.RUNTIME_MANIFEST: _runtime(),
            "examples/agent-ts/package.json": {
                "name": "agent-ts",
                "dependencies": {"@mcpmesh/sdk": "^3.3.2"},
            },
        },
    )
    found = cne.violations(root)
    assert len(found) == 1, found
    assert "declares no engines.node" in found[0]


def test_a_devdependency_on_the_runtime_counts(tmp_path):
    root = _repo(
        tmp_path,
        {
            cne.RUNTIME_MANIFEST: _runtime(),
            "fixtures/x/package.json": {
                "name": "x",
                "engines": {"node": ">=8"},
                "devDependencies": {"@mcpmesh/core": "file:../.."},
            },
        },
    )
    assert len(cne.violations(root)) == 1


def test_raising_the_runtime_floor_turns_a_compliant_tree_red(tmp_path):
    """The point of deriving the floor. Same example, unchanged; only the
    runtime moves — and the example is now under-declared without anyone
    editing it. This is the drift the 44 files were re-set for."""
    files = {
        cne.RUNTIME_MANIFEST: _runtime(">=22.0.0"),
        "examples/agent-ts/package.json": {
            "name": "agent-ts",
            "engines": {"node": ">=22.0.0"},
            "dependencies": {"@mcpmesh/sdk": "^3.3.2"},
        },
    }
    root = _repo(tmp_path, files)
    assert cne.violations(root) == []

    (root / cne.RUNTIME_MANIFEST).write_text(
        json.dumps(_runtime(">=99.0.0"), indent=2) + "\n"
    )
    found = cne.violations(root)
    assert len(found) == 1, found
    assert ">=99.0.0" in found[0]


# --------------------------------------------------------------------------
# The npm/cli shape must stay clean without an allowlist entry
# --------------------------------------------------------------------------


def test_the_cli_wrapper_shape_is_not_flagged(tmp_path):
    """`npm/cli` declares `>=18` and optionally depends on
    `@mcpmesh/cli-{linux,darwin}-{x64,arm64}` — prebuilt Go binaries, not the
    TypeScript runtime — so `>=18` is an accurate claim about what it needs.

    This is why the rule keys on `@mcpmesh/sdk`/`@mcpmesh/core` rather than on
    the `@mcpmesh/*` scope: the scope-wide rule #1420 proposed would flag this
    package and need an allowlist entry to un-flag it. An allowlist is a
    standing invitation to add the next one."""
    root = _repo(
        tmp_path,
        {
            cne.RUNTIME_MANIFEST: _runtime(),
            "npm/cli/package.json": {
                "name": "@mcpmesh/cli",
                "engines": {"node": ">=18"},
                "optionalDependencies": {
                    "@mcpmesh/cli-linux-x64": "3.3.2",
                    "@mcpmesh/cli-darwin-arm64": "3.3.2",
                },
            },
        },
    )
    assert cne.violations(root) == []


def test_the_real_cli_wrapper_still_declares_18():
    """Belt and braces: the sweep must not have swept it."""
    data = json.loads((PROJECT_ROOT / "npm/cli/package.json").read_text())
    assert data["engines"]["node"] == ">=18"
    assert not cne.depends_on_runtime(data)


def test_the_runtime_packages_are_not_checked_against_themselves(tmp_path):
    """`@mcpmesh/sdk` depends on `@mcpmesh/core`, so without the exclusion the
    runtime manifest would be checked against its own floor — and
    `@mcpmesh/core`, which declares no engines, would be reported as an
    under-declared consumer of the runtime it *is*."""
    root = _repo(
        tmp_path,
        {
            cne.RUNTIME_MANIFEST: {
                "name": "@mcpmesh/sdk",
                "engines": {"node": ">=22.0.0"},
                "dependencies": {"@mcpmesh/core": "file:../core/typescript"},
            },
            "src/runtime/core/typescript/package.json": {"name": "@mcpmesh/core"},
        },
    )
    assert cne.violations(root) == []


if __name__ == "__main__":
    import tempfile

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        if fn.__code__.co_argcount:
            with tempfile.TemporaryDirectory() as d:
                fn(pathlib.Path(d))
        else:
            fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed")
