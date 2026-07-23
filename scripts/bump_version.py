#!/usr/bin/env python3
"""
Bump the mcp-mesh version across the entire codebase.

Usage:
    python scripts/bump_version.py <old_version> <new_version>
    python scripts/bump_version.py 0.9.1 0.9.2
    python scripts/bump_version.py 0.9.1 0.9.2-beta.1
    python scripts/bump_version.py 0.9.1 0.9.2 --dry-run

Beta support:
    Versions like 0.9.2-beta.1 are automatically converted to PEP 440
    format (0.9.2b1) for Python/PyPI files.

Design:
    Most version replacements are declared as Handler entries in HANDLERS.
    A handler describes which files to scan (globs/excludes), what regex to
    apply, and which projection of the version to substitute (raw / pep440 /
    minor / scaffold-tag). A small number of edge cases that need bespoke
    logic (Helm Charts.yaml multi-pattern, Test Config multi-key, etc.)
    remain as functions and are invoked alongside the handlers.
"""

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


def to_pep440(version: str) -> str:
    """Convert a semver-style version to PEP 440 format.

    Examples:
        0.9.2       -> 0.9.2
        0.9.2-beta.1 -> 0.9.2b1
        0.9.2-alpha.3 -> 0.9.2a3
        0.9.2-rc.2   -> 0.9.2rc2
    """
    m = re.match(r"^(\d+\.\d+\.\d+)-beta\.(\d+)$", version)
    if m:
        return f"{m.group(1)}b{m.group(2)}"
    m = re.match(r"^(\d+\.\d+\.\d+)-alpha\.(\d+)$", version)
    if m:
        return f"{m.group(1)}a{m.group(2)}"
    m = re.match(r"^(\d+\.\d+\.\d+)-rc\.(\d+)$", version)
    if m:
        return f"{m.group(1)}rc{m.group(2)}"
    return version


def to_minor(version: str) -> str:
    """Drop patch and prerelease, e.g. 1.3.0-beta.1 -> 1.3."""
    m = re.match(r"^(\d+)\.(\d+)", version)
    if not m:
        return version
    return f"{m.group(1)}.{m.group(2)}"


def format_version(version: str, version_format: str) -> str:
    if version_format == "raw":
        return version
    if version_format == "pep440":
        return to_pep440(version)
    if version_format == "minor":
        return to_minor(version)
    raise ValueError(f"unknown version_format: {version_format}")


# ---------------------------------------------------------------------------
# File replacement helpers
# ---------------------------------------------------------------------------


def replace_in_file(
    filepath: Path,
    pattern: str,
    replacement: str,
    dry_run: bool,
    flags: int = 0,
) -> bool:
    """Apply a regex replacement in a file. Returns True if changes were made."""
    if not filepath.exists():
        return False
    content = filepath.read_text()
    new_content = re.sub(pattern, replacement, content, flags=flags)
    if new_content == content:
        return False
    if not dry_run:
        filepath.write_text(new_content)
    return True


# ---------------------------------------------------------------------------
# Handler definition + executor
# ---------------------------------------------------------------------------


@dataclass
class Handler:
    name: str
    globs: list[str]
    pattern: str
    replacement: str
    excludes: list[str] = field(default_factory=list)
    version_format: str = "raw"  # "raw" | "pep440" | "minor" | "scaffold-tag"
    flags: int = 0
    # Optional cosmetic suffix appended to each reported file path. Useful
    # when two handlers update the same file but you want to disambiguate
    # them in the report (e.g. the mcp-mesh-core dep entry in pypi).
    report_suffix: str = ""


def _glob_to_regex(pattern: str) -> re.Pattern:
    """Translate a glob pattern (with `**`, `*`, `?`) to a regex.

    `**` (followed by `/` or end) matches any number of path components.
    `*` matches any sequence of characters except `/`.
    `?` matches a single non-`/` character.
    """
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern[i : i + 3] == "**/":
            parts.append("(?:.*/)?")
            i += 3
        elif pattern[i : i + 2] == "**":
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(parts) + "$")


# Directory names never worth descending into: they hold no first-party
# version pins we bump, but (especially node_modules) are enormous and, when
# combined with the tutorial/example symlink webs, blow up the walk time.
# Excludes still filter results defensively; pruning here is a pure speedup.
_WALK_PRUNE_DIRS = frozenset({"node_modules", ".git", ".venv"})


def _walk_files(base: Path):
    """Recursively yield every file under `base`, following symlinks but
    detecting cycles by tracking realpaths in the current ancestor chain.

    Uses a stack so each branch carries its own ancestor set — multiple
    symlinks pointing to the same target are still each visited (we only
    skip a directory if descending would re-enter one of OUR ancestors).
    Directories in `_WALK_PRUNE_DIRS` are not descended into.
    """
    if not base.exists():
        return
    base_str = str(base)
    stack: list[tuple[str, frozenset[str]]] = [
        (base_str, frozenset({os.path.realpath(base_str)}))
    ]
    while stack:
        dirpath, ancestors = stack.pop()
        try:
            entries = list(os.scandir(dirpath))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_file(follow_symlinks=True):
                    yield Path(e.path)
                elif e.is_dir(follow_symlinks=True):
                    if e.name in _WALK_PRUNE_DIRS:
                        continue
                    rp = os.path.realpath(e.path)
                    if rp in ancestors:
                        continue
                    stack.append((e.path, ancestors | {rp}))
            except OSError:
                continue


def _glob_files(globs: list[str]) -> set[Path]:
    """Resolve a list of glob patterns (relative to PROJECT_ROOT) into the set
    of matching files. Symlinks (including symlinked directories) are
    followed — necessary because integration test artifacts and tutorial
    scaffolds use symlinks heavily."""
    files: set[Path] = set()
    for g in globs:
        # Determine the static directory prefix (everything up to the first
        # wildcard). We walk that directory and match each candidate.
        static_parts: list[str] = []
        for part in g.split("/"):
            if any(c in part for c in "*?["):
                break
            static_parts.append(part)
        static = "/".join(static_parts)
        base = PROJECT_ROOT / static if static else PROJECT_ROOT

        # Fast path: pattern has no wildcards — just check the file directly.
        if static == g:
            if base.is_file():
                files.add(base)
            continue

        rgx = _glob_to_regex(g)
        for f in _walk_files(base):
            try:
                rel = f.relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                continue
            if rgx.match(rel):
                files.add(f)
    return files


def run_handler(handler: Handler, old: str, new: str, dry_run: bool) -> list[str]:
    old_v = format_version(old, handler.version_format)
    new_v = format_version(new, handler.version_format)
    pattern = handler.pattern.replace("OLD", re.escape(old_v))
    replacement = handler.replacement.replace("NEW", new_v)

    files = _glob_files(handler.globs)
    if handler.excludes:
        files -= _glob_files(handler.excludes)

    changed: list[str] = []
    for f in sorted(files):
        if replace_in_file(f, pattern, replacement, dry_run, flags=handler.flags):
            label = str(f.relative_to(PROJECT_ROOT))
            if handler.report_suffix:
                label = f"{label} {handler.report_suffix}"
            changed.append(label)
    return changed


# ---------------------------------------------------------------------------
# Handler list (migrated from the original 20 category functions plus new
# handlers that catch previously-missed stale references).
# ---------------------------------------------------------------------------


HANDLERS: list[Handler] = [
    # --- Category 1: Python Packages (pyproject.toml version field) -------
    Handler(
        name="Python Packages (pyproject.toml)",
        globs=[
            "packaging/pypi/pyproject.toml",
            "src/runtime/python/pyproject.toml",
            "src/runtime/core/pyproject.toml",
        ],
        pattern=r'(version\s*=\s*")OLD(")',
        replacement=r"\g<1>NEW\2",
        version_format="pep440",
    ),
    Handler(
        name="Python Packages (__init__.py __version__)",
        globs=[
            "src/runtime/python/_mcp_mesh/__init__.py",
            "src/runtime/python/mesh/__init__.py",
        ],
        pattern=r'(__version__\s*=\s*")OLD(")',
        replacement=r"\g<1>NEW\2",
        version_format="pep440",
    ),
    # --- Category 2: Python OUR dependencies ------------------------------
    Handler(
        name="Python Dependencies (mcp-mesh-core)",
        globs=["packaging/pypi/pyproject.toml"],
        pattern=r'("mcp-mesh-core>=)OLD(")',
        replacement=r"\g<1>NEW\2",
        version_format="pep440",
        report_suffix="(mcp-mesh-core dep)",
    ),
    # --- Category 3: TypeScript/Node.js Packages --------------------------
    Handler(
        name="TypeScript/Node.js Packages",
        globs=[
            "src/runtime/typescript/package.json",
            "src/runtime/core/typescript/package.json",
            "npm/cli/package.json",
        ],
        pattern=r'("version":\s*")OLD(")',
        replacement=r"\g<1>NEW\2",
    ),
    # --- Category 4: TypeScript Dependencies (@mcpmesh/*) -----------------
    Handler(
        name="TypeScript Dependencies (@mcpmesh/*)",
        globs=[
            "npm/cli/package.json",
            "src/runtime/typescript/package.json",
        ],
        pattern=r'("@mcpmesh/[^"]+?":\s*")(\^?)OLD(")',
        replacement=r"\g<1>\g<2>NEW\3",
    ),
    # --- Category 5: Java Parent/Module POMs ------------------------------
    # Only rewrite the mcp-mesh-owned <version>, i.e. the one that directly
    # follows an `io.mcp-mesh` <groupId>/<artifactId> pair (the project coords
    # or a <parent> block). A blind `<version>OLD</version>` replace also
    # catches coincidental third-party plugin/dependency pins that happen to
    # sit at the same version (e.g. maven-jar-plugin 3.3.0), which broke the
    # 3.3.1 release when it bumped them to a nonexistent 3.3.1 plugin.
    Handler(
        name="Java Parent/Module POMs",
        globs=[
            "src/runtime/java/pom.xml",
            "src/runtime/java/mcp-mesh-bom/pom.xml",
            "src/runtime/java/mcp-mesh-core/pom.xml",
            "src/runtime/java/mcp-mesh-sdk/pom.xml",
            "src/runtime/java/mcp-mesh-spring-boot-starter/pom.xml",
            "src/runtime/java/mcp-mesh-spring-ai/pom.xml",
            "src/runtime/java/mcp-mesh-native/pom.xml",
        ],
        pattern=(
            r"(<groupId>io\.mcp-mesh</groupId>\s*"
            r"<artifactId>[^<]+</artifactId>\s*<version>)OLD(</version>)"
        ),
        replacement=r"\g<1>NEW\2",
    ),
    # --- Category 6: Java Example POMs ------------------------------------
    # Recurse the whole examples/ tree (multi-module examples nest POMs under
    # subdirs like benchmark-chain/svc-a/pom.xml that the old two shallow
    # globs missed). node_modules excluded defensively.
    Handler(
        name="Java Example POMs",
        globs=["examples/**/pom.xml"],
        excludes=["**/node_modules/**"],
        pattern=r"(<mcp-mesh\.version>)OLD(</mcp-mesh\.version>)",
        replacement=r"\g<1>NEW\2",
    ),
    # --- Category 7: Rust Cargo.toml --------------------------------------
    Handler(
        name="Rust Cargo.toml",
        globs=["src/runtime/core/Cargo.toml"],
        pattern=r'(version\s*=\s*")OLD(")',
        replacement=r"\g<1>NEW\2",
    ),
    # --- Category 9: Package Managers (Homebrew + Scoop) ------------------
    Handler(
        name="Package Managers (Homebrew)",
        globs=["packaging/homebrew/mcp-mesh.rb"],
        pattern=r'(version\s+")OLD(")',
        replacement=r"\g<1>NEW\2",
    ),
    Handler(
        name="Package Managers (Scoop)",
        globs=["packaging/scoop/mcp-mesh.json"],
        pattern=r'("version":\s*")OLD(")',
        replacement=r"\g<1>NEW\2",
    ),
    # --- Category 10: Go Handler Templates --------------------------------
    Handler(
        name="Go Handler Templates (python_handler.go pip dep)",
        globs=["src/core/cli/handlers/python_handler.go"],
        pattern=r"(mcp-mesh>=)OLD",
        replacement=r"\g<1>NEW",
        version_format="pep440",
    ),
    Handler(
        name="Go Handler Templates (typescript_handler.go @mcpmesh/sdk)",
        globs=["src/core/cli/handlers/typescript_handler.go"],
        pattern=r'("@mcpmesh/sdk":\s*"\^)OLD(")',
        replacement=r"\g<1>NEW\2",
    ),
    Handler(
        name="Go Handler Templates (java_handler.go <version>)",
        globs=["src/core/cli/handlers/java_handler.go"],
        pattern=r"(<version>)OLD(</version>)",
        replacement=r"\g<1>NEW\2",
    ),
    Handler(
        name="Go Handler Templates (language_test.go pip dep)",
        globs=["src/core/cli/handlers/language_test.go"],
        pattern=r"(mcp-mesh==)OLD",
        replacement=r"\g<1>NEW",
        version_format="pep440",
    ),
    # --- Category 11: Scaffold Templates ----------------------------------
    Handler(
        name="Scaffold Templates (Java pom.xml.tmpl)",
        globs=["cmd/meshctl/templates/java/*/pom.xml.tmpl"],
        pattern=r"(<mcp-mesh\.version>)OLD(</mcp-mesh\.version>)",
        replacement=r"\g<1>NEW\2",
    ),
    Handler(
        name="Scaffold Templates (TypeScript package.json.tmpl)",
        globs=["cmd/meshctl/templates/typescript/*/package.json.tmpl"],
        pattern=r'("@mcpmesh/sdk":\s*"\^)OLD(")',
        replacement=r"\g<1>NEW\2",
    ),
    # --- Category 12: Documentation (markdown) ----------------------------
    # Three patterns: --version OLD, <version>OLD</version>, vOLD.
    Handler(
        name="Documentation (--version OLD)",
        globs=[
            "docs/**/*.md",
            "src/core/cli/man/content/**/*.md",
        ],
        pattern=r"(--version\s+)OLD",
        replacement=r"\g<1>NEW",
    ),
    Handler(
        name="Documentation (<version>OLD</version>)",
        globs=[
            "docs/**/*.md",
            "src/core/cli/man/content/**/*.md",
        ],
        pattern=r"(<version>)OLD(</version>)",
        replacement=r"\g<1>NEW\2",
    ),
    Handler(
        name="Documentation (vOLD)",
        globs=[
            "docs/**/*.md",
            "src/core/cli/man/content/**/*.md",
        ],
        # Word boundary, not preceded by / so URLs aren't touched.
        pattern=r"(?<!/)vOLD(?=[\s,\)\]\"']|$)",
        replacement=r"vNEW",
        flags=re.MULTILINE,
    ),
    # --- Category 14: Example agent requirements.txt ---------------------
    Handler(
        name="Example Requirements (requirements.txt)",
        globs=["examples/docker-examples/agents/*/requirements.txt"],
        pattern=r"(mcp-mesh>=)OLD",
        replacement=r"\g<1>NEW",
        version_format="pep440",
    ),
    # --- Category 15: CI/CD Workflows ------------------------------------
    Handler(
        name="CI/CD Workflows (default: \"vOLD\")",
        globs=[
            ".github/workflows/release.yml",
            ".github/workflows/helm-release.yml",
        ],
        pattern=r'(default:\s*"v)OLD(")',
        replacement=r"\g<1>NEW\2",
    ),
    Handler(
        name="CI/CD Workflows (e.g., vOLD)",
        globs=[
            ".github/workflows/release.yml",
            ".github/workflows/helm-release.yml",
        ],
        pattern=r"(e\.g\.,\s*v)OLD",
        replacement=r"\g<1>NEW",
    ),
    # --- Category 16: TypeScript Example Packages (@mcpmesh/*) -----------
    # Recurse the whole examples/ tree (was limited to toolcalls/*-ts). The
    # version regex only matches pinned versions, so `file:` workspace refs
    # (e.g. "@mcpmesh/sdk": "file:../..") are left untouched. node_modules
    # excluded so vendored packages aren't rewritten.
    Handler(
        name="TypeScript Example Packages (@mcpmesh/*)",
        globs=["examples/**/package.json"],
        excludes=["**/node_modules/**"],
        # Match "@mcpmesh/x": "OLD" or "@mcpmesh/x": "^OLD" (replace with ^NEW)
        pattern=r'("@mcpmesh/[^"]+?":\s*")\^?OLD(")',
        replacement=r"\g<1>^NEW\2",
    ),
    # --- Category 17: Docker Example Helm Values --------------------------
    Handler(
        name="Docker Example Helm Values",
        globs=["examples/docker-examples/agents/*/helm-values.yaml"],
        pattern=r"(--version\s+)OLD",
        replacement=r"\g<1>NEW",
    ),
    # --- Category 18: Integration Test Artifacts --------------------------
    Handler(
        name="Integration Test Artifacts (package.json)",
        globs=["tests/integration/suites/**/package.json"],
        excludes=["**/node_modules/**"],
        pattern=r'("@mcpmesh/[^"]+?":\s*")(\^?)OLD(")',
        replacement=r"\g<1>\g<2>NEW\3",
    ),
    Handler(
        name="Integration Test Artifacts (pom.xml)",
        globs=["tests/integration/suites/**/pom.xml"],
        pattern=r"(<mcp-mesh\.version>)OLD(</mcp-mesh\.version>)",
        replacement=r"\g<1>NEW\2",
    ),
    # --- Category 20: Docker Image Tags (Scaffold Dockerfile templates) --
    # Dockerfile templates use full version tags (mcpmesh/python-runtime:1.3.0)
    Handler(
        name="Docker Image Tags (Scaffold Dockerfile.tmpl)",
        globs=["cmd/meshctl/templates/*/*/Dockerfile.tmpl"],
        pattern=(
            r"(mcpmesh/(?:python-runtime|typescript-runtime|java-runtime):)[^\s]+"
        ),
        replacement=r"\g<1>NEW",
    ),
    # --- NEW: Docker tags in markdown (man content + docs + helm READMEs)
    # Pattern uses (?![\d.\-+]) negative lookahead so `:1.3.1` doesn't match
    # the prefix of `:1.3.10`, `:1.3.1-rc.2`, `:1.3.1.0`, or `:1.3.1+build`.
    Handler(
        name="Docker Image Tags in Markdown",
        globs=[
            "docs/**/*.md",
            "src/core/cli/man/content/**/*.md",
            "helm/*/README.md",
        ],
        excludes=["docs/downloads/**"],
        pattern=(
            r"(mcpmesh/(?:registry|python-runtime|typescript-runtime"
            r"|java-runtime|ui|cli):)OLD(?![\d.\-+])"
        ),
        replacement=r"\g<1>NEW",
    ),
    # --- NEW: Docker tags in example + integration test Dockerfiles ------
    Handler(
        name="Docker Image Tags in Dockerfiles",
        globs=[
            "examples/**/Dockerfile",
            "tests/integration/suites/**/Dockerfile",
        ],
        excludes=[
            # uc20_tutorial uses symlinks back into examples/tutorial/**
            "tests/integration/suites/uc20_tutorial/**",
            "**/node_modules/**",
        ],
        pattern=(
            r"(FROM mcpmesh/(?:registry|python-runtime|typescript-runtime"
            r"|java-runtime|ui|cli):)OLD(?![\d.\-+])"
        ),
        replacement=r"\g<1>NEW",
    ),
    # --- NEW: Docker tags in docker-compose.yml + variants ---------------
    # Matches both `image: mcpmesh/...:VER` lines AND bare `mcpmesh/...:VER`
    # references in YAML comments (e.g., the file header that describes services)
    Handler(
        name="Docker Image Tags in docker-compose",
        globs=[
            "examples/**/docker-compose.yml",
            "examples/**/docker-compose.*.yml",
        ],
        excludes=["**/node_modules/**"],
        pattern=(
            r"(mcpmesh/(?:registry|python-runtime|typescript-runtime"
            r"|java-runtime|ui|cli):)OLD(?![\d.\-+])"
        ),
        replacement=r"\g<1>NEW",
    ),
    # --- NEW: Hardcoded image tags inside Go handler source --------------
    Handler(
        name="Go Handler Hardcoded Image Tags",
        globs=[
            "src/core/cli/handlers/python_handler.go",
            "src/core/cli/handlers/typescript_handler.go",
            "src/core/cli/handlers/java_handler.go",
        ],
        pattern=(
            r"(mcpmesh/(?:registry|python-runtime|typescript-runtime"
            r"|java-runtime|ui|cli):)OLD(?![\d.\-+])"
        ),
        replacement=r"\g<1>NEW",
    ),
    # --- NEW: Scaffold help text + scaffold tests + handler tests --------
    # Full version form (e.g., 1.3.0) appears in scaffold.go help text and
    # in compose.go template strings + compose_test.go expected output.
    Handler(
        name="Scaffold Source Hardcoded Image Tags (full version)",
        globs=[
            "src/core/cli/scaffold.go",
            "src/core/cli/scaffold/compose.go",
            "src/core/cli/scaffold/compose_test.go",
        ],
        pattern=(
            r"(mcpmesh/(?:registry|python-runtime|typescript-runtime"
            r"|java-runtime|ui|cli):)OLD(?![\d.\-+])"
        ),
        replacement=r"\g<1>NEW",
    ),
    # --- NEW: language_test.go pins the FULL release tag (e.g., :1.3.0) --
    # TestPythonHandler_GetDockerImage / TestTypeScriptHandler_GetDockerImage
    # assert the exact tag GetDockerImage() returns, so their expected literal
    # must track the full version (was minor, which never matched the full tag
    # the handlers return — the loose assertion missed the 2.8.0 partial bump).
    Handler(
        name="Language Test Hardcoded Image Tags (full version)",
        globs=["src/core/cli/handlers/language_test.go"],
        pattern=(
            r"(mcpmesh/(?:registry|python-runtime|typescript-runtime"
            r"|java-runtime|ui|cli):)OLD(?![\d.\-+])"
        ),
        replacement=r"\g<1>NEW",
    ),
]


# ---------------------------------------------------------------------------
# Bespoke handlers (kept as functions because they have multi-pattern logic
# or conditional behavior that a single Handler can't express cleanly)
# ---------------------------------------------------------------------------


def bump_helm_charts(old: str, new: str, dry_run: bool) -> list[str]:
    """Helm Chart.yaml + Chart.lock + values.yaml image tag (minor)."""
    changed: list[str] = []
    helm_dir = PROJECT_ROOT / "helm"
    if not helm_dir.exists():
        return changed

    # Chart.yaml files: three patterns per file.
    for chart_yaml in sorted(helm_dir.glob("*/Chart.yaml")):
        file_changed = False
        # version: OLD (top-level chart version, start of line)
        p1 = rf"(^version:\s*){re.escape(old)}$"
        if replace_in_file(chart_yaml, p1, rf"\g<1>{new}", dry_run, flags=re.MULTILINE):
            file_changed = True
        # appVersion: "OLD"
        p2 = rf'(appVersion:\s*"){re.escape(old)}(")'
        if replace_in_file(chart_yaml, p2, rf"\g<1>{new}\2", dry_run):
            file_changed = True
        # dependency version: "OLD" (indented, in dependencies section)
        p3 = rf'(    version:\s*"){re.escape(old)}(")'
        if replace_in_file(chart_yaml, p3, rf"\g<1>{new}\2", dry_run):
            file_changed = True
        if file_changed:
            changed.append(str(chart_yaml.relative_to(PROJECT_ROOT)))

    # Chart.lock file
    chart_lock = helm_dir / "mcp-mesh-core" / "Chart.lock"
    if chart_lock.exists():
        pattern = rf"(  version:\s*){re.escape(old)}$"
        if replace_in_file(
            chart_lock, pattern, rf"\g<1>{new}", dry_run, flags=re.MULTILINE
        ):
            changed.append(str(chart_lock.relative_to(PROJECT_ROOT)))

    # values.yaml image tags (minor version format, only mcp-mesh charts)
    old_minor = to_minor(old)
    new_minor = to_minor(new)
    if old_minor != new_minor:
        mcp_mesh_charts = [
            "mcp-mesh-registry",
            "mcp-mesh-agent",
            "mcp-mesh-ui",
            "mcp-mesh-core",
        ]
        for chart_name in mcp_mesh_charts:
            values_yaml = helm_dir / chart_name / "values.yaml"
            if values_yaml.exists():
                pattern = rf'(tag:\s*"){re.escape(old_minor)}(")'
                replacement = rf"\g<1>{new_minor}\2"
                if replace_in_file(values_yaml, pattern, replacement, dry_run):
                    changed.append(str(values_yaml.relative_to(PROJECT_ROOT)))

    return changed


def bump_test_config(old: str, new: str, dry_run: bool) -> list[str]:
    """tests/lib-tests/config.yaml — multiple keys, mixed formats."""
    changed: list[str] = []
    f = PROJECT_ROOT / "tests" / "lib-tests" / "config.yaml"
    if not f.exists():
        return changed

    content = f.read_text()
    old_pep440 = to_pep440(old)
    new_pep440 = to_pep440(new)
    new_content = content

    for key in [
        "cli_version",
        "sdk_typescript_version",
        "core_version",
        "sdk_java_version",
    ]:
        p = rf'({key}:\s*"){re.escape(old)}(")'
        new_content = re.sub(p, rf"\g<1>{new}\2", new_content)

    p = rf'(sdk_python_version:\s*"){re.escape(old_pep440)}(")'
    new_content = re.sub(p, rf"\g<1>{new_pep440}\2", new_content)

    if new_content != content:
        if not dry_run:
            f.write_text(new_content)
        changed.append(str(f.relative_to(PROJECT_ROOT)))

    return changed


def bump_test_documentation(old: str, new: str, dry_run: bool) -> list[str]:
    """Test documentation README files use a plain string replace."""
    changed: list[str] = []
    files = [
        PROJECT_ROOT / "tests" / "integration" / "README.md",
        PROJECT_ROOT / "tests" / "integration" / "suites" / "README.md",
        PROJECT_ROOT / "tests" / "lib-tests" / "README.md",
    ]
    for f in files:
        if not f.exists():
            continue
        content = f.read_text()
        new_content = content.replace(old, new)
        if new_content != content:
            if not dry_run:
                f.write_text(new_content)
            changed.append(str(f.relative_to(PROJECT_ROOT)))
    return changed


# ---------------------------------------------------------------------------
# Post-bump coverage guard
# ---------------------------------------------------------------------------

# Files whose stale version strings are intentional history or fixtures, not
# live pins. Both bump_version.py and test_bump_version.py carry version-shaped
# example literals by design: the bump script's guard docstrings/examples embed
# illustrative tags (e.g. ``tag: "2.8"``), and the test holds old/new literals to
# exercise the guard regexes themselves, so it always carries the previous version.
_GUARD_ALLOWLIST_FILES = re.compile(
    r"(?:^|/)(?:RELEASE_NOTES\.md|CHANGELOG[^/]*|(?:test_)?bump_version\.py)$"
)

# Lines mentioning these third-party projects legitimately carry their OWN
# versions, which can collide numerically with ours.
_GUARD_ALLOWLIST_TOKENS = (
    "spiffe",
    "xyflow",
    "python-dateutil",
    "dateutil",
    "grafana-tempo",
    "grafana/tempo",
    "/tempo:",
    "tempo_",
    "tempo/releases",
)


def _guard_patterns(old: str, new: str | None = None) -> list[re.Pattern]:
    """Mesh-shaped contexts in which a surviving OLD version = a missed bump.

    ``new`` lets the guard tell a patch bump from a minor/major one. The
    minor-version image tag (e.g. ``tag: "2.8"``) intentionally tracks the
    latest patch, so it is only stale when the MINOR changes — for a patch
    bump it is left in place by design. When ``new`` is omitted the minor-tag
    pattern is included (the conservative "could be stale" default)."""
    o = re.escape(old)
    om = re.escape(to_minor(old))
    op = re.escape(to_pep440(old))
    img = (
        r"mcpmesh/(?:registry|python-runtime|typescript-runtime"
        r"|java-runtime|ui|cli):"
    )
    boundary = r"(?![\d.\-+])"
    patterns = [
        re.compile(img + o + boundary),
        re.compile(r"mcp-mesh(?:>=|==)" + op),
        # package.json: "@mcpmesh/sdk": "^X" / "@mcpmesh/core": "X" (the key
        # quote, ": ", then the value's opening quote sit between the package
        # name and the version), plus the npm `@mcpmesh/sdk@^X` shorthand.
        re.compile(
            r"@mcpmesh/[^\"'@\s]+(?:[\"']\s*:\s*[\"']|@)\^?" + o + boundary
        ),
        re.compile(r"<mcp-mesh\.version>" + o + r"</mcp-mesh\.version>"),
        re.compile(r"--version\s+v?" + o + boundary),
        re.compile(r'tag:\s*"' + o + r'"'),
    ]
    if new is None or to_minor(old) != to_minor(new):
        patterns.append(re.compile(r'tag:\s*"' + om + r'"'))
    return patterns


def coverage_guard(old: str, new: str) -> tuple[bool, list[str]]:
    """Final safety net: after a bump, scan every tracked file for mesh-shaped
    references that still carry the OLD version.

    Returns ``(ran, survivors)``. ``ran`` is False when the scan could not
    execute (git unavailable / errored) — the caller must fail closed rather
    than treat that as clean. When ``ran`` is True, ``survivors`` is the list
    of 'path:lineno: text' hits (empty = clean). Vendored trees (node_modules)
    and history files are skipped; third-party version pins on the same line
    are allowlisted."""
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return (False, [])

    patterns = _guard_patterns(old, new)
    survivors: list[str] = []
    for rel in out.splitlines():
        if not rel:
            continue
        if "node_modules/" in rel or _GUARD_ALLOWLIST_FILES.search(rel):
            continue
        try:
            text = (PROJECT_ROOT / rel).read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(tok in line for tok in _GUARD_ALLOWLIST_TOKENS):
                continue
            if any(p.search(line) for p in patterns):
                survivors.append(f"{rel}:{lineno}: {line.strip()}")
    return (True, survivors)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _merge_changes(
    accumulator: dict[str, list[str]], name: str, files: list[str]
) -> None:
    """Append a category's changes preserving insertion order."""
    if name in accumulator:
        existing = accumulator[name]
        for f in files:
            if f not in existing:
                existing.append(f)
    else:
        accumulator[name] = list(files)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bump the mcp-mesh version across the entire codebase."
    )
    parser.add_argument("old_version", help="Current version (e.g., 0.9.1)")
    parser.add_argument("new_version", help="New version (e.g., 0.9.2 or 0.9.2-beta.1)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files",
    )
    args = parser.parse_args()

    old = args.old_version
    new = args.new_version
    dry_run = args.dry_run
    new_pep440 = to_pep440(new)

    if dry_run:
        print(f"[DRY RUN] Version bump: {old} -> {new}")
    else:
        print(f"Version bump: {old} -> {new}")

    if new_pep440 != new:
        print(f"PEP 440 format: {new_pep440}")
    print()

    # Run handlers, grouping per handler name. Some handlers share categories
    # at the report level (e.g., several "Documentation" sub-handlers).
    categories: dict[str, list[str]] = {}

    for handler in HANDLERS:
        files = run_handler(handler, old, new, dry_run)
        _merge_changes(categories, handler.name, files)

    # Bespoke handlers that don't fit the declarative shape.
    _merge_changes(categories, "Helm Charts", bump_helm_charts(old, new, dry_run))
    _merge_changes(categories, "Test Config", bump_test_config(old, new, dry_run))
    _merge_changes(
        categories, "Test Documentation", bump_test_documentation(old, new, dry_run)
    )

    # Print results.
    total_files = 0
    total_categories = 0
    for name, files in categories.items():
        print(f"Category: {name}")
        if files:
            total_categories += 1
            for f in files:
                prefix = "[DRY RUN] Would update" if dry_run else "  +"
                print(f"  {prefix} {f}")
            total_files += len(files)
        else:
            print("  (no changes)")
        print()

    if dry_run:
        print(
            f"[DRY RUN] Would update {total_files} files across "
            f"{total_categories} categories"
        )
    else:
        print(
            f"Summary: {total_files} files updated across {total_categories} categories"
        )

    chart_lock = PROJECT_ROOT / "helm" / "mcp-mesh-core" / "Chart.lock"
    if chart_lock.exists():
        print()
        print(
            "Reminder: run 'helm dependency update helm/mcp-mesh-core' "
            "to regenerate Chart.lock digest"
        )

    cargo_lock = PROJECT_ROOT / "src" / "runtime" / "core" / "Cargo.lock"
    if cargo_lock.exists():
        print()
        print(
            "Reminder: run 'cargo generate-lockfile' in src/runtime/core "
            "to refresh Cargo.lock with the new mcp-mesh-core version"
        )

    # Final step: verify no mesh-shaped reference to the OLD version survived.
    # Skipped on --dry-run (nothing was written, so every ref would "survive").
    if not dry_run:
        ran, survivors = coverage_guard(old, new)
        print()
        if not ran:
            print(
                "❌ Coverage guard did NOT run (git ls-files unavailable or "
                "errored). Failing closed — cannot confirm the bump is "
                "complete. Re-run from a git checkout with git on PATH."
            )
            return 1
        if survivors:
            print(
                f"❌ Coverage guard: {len(survivors)} stale mesh-shaped "
                f"reference(s) to {old} survived the bump:"
            )
            for s in survivors:
                print(f"  {s}")
            print(
                "Add or broaden a handler in scripts/bump_version.py to cover "
                "these, then re-run."
            )
            return 1
        print(f"✅ Coverage guard: no stale mesh-shaped references to {old} remain.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
