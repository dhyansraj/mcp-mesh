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

    Two guards run at the end and can fail the bump:
      - coverage_guard   — did we MISS a mesh version? (false negatives)
      - overmatch_guard  — did we rewrite something that ISN'T ours?
"""

import argparse
import difflib
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
# Change recording (feeds the post-bump over-match guard)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChangedLine:
    path: str  # repo-relative POSIX path
    lineno: int  # 1-based line number in the post-bump content
    text: str  # the line as it reads AFTER the replacement
    source: str  # handler / bespoke-step label that rewrote it
    # The file's content (as a line list) right after THIS replacement, so the
    # over-match guard can read a changed line's neighbours even under
    # --dry-run. Held per record rather than in a file-keyed dict: 11 file
    # patterns are targeted by more than one handler (docs/**/*.md by four),
    # and a shared dict would resolve an earlier handler's line numbers
    # against a later handler's content. `record_changes` builds a fresh list
    # per replacement and never mutates it, so sharing the reference is safe.
    # Excluded from eq/hash so ChangedLine stays hashable and comparable.
    snapshot: list[str] = field(default_factory=list, compare=False, repr=False)


# Every line any handler rewrote, in application order.
_CHANGE_LOG: list[ChangedLine] = []


def reset_change_log() -> None:
    """Clear the recorded changes. Call once at the start of a bump."""
    _CHANGE_LOG.clear()


def record_changes(
    filepath: Path, old_content: str, new_content: str, source: str
) -> None:
    """Record which individual lines a replacement rewrote.

    The guard needs to know what we changed without shelling out to
    `git diff`: the script must stay self-contained, work on a dirty tree,
    and work under --dry-run, where the change exists only in memory.
    """
    try:
        rel = filepath.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        rel = str(filepath)
    new_lines = new_content.splitlines()
    matcher = difflib.SequenceMatcher(
        a=old_content.splitlines(), b=new_lines, autojunk=False
    )
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            for j in range(j1, j2):
                _CHANGE_LOG.append(
                    ChangedLine(rel, j + 1, new_lines[j], source, new_lines)
                )


# ---------------------------------------------------------------------------
# File replacement helpers
# ---------------------------------------------------------------------------


def replace_in_file(
    filepath: Path,
    pattern: str,
    replacement: str,
    dry_run: bool,
    flags: int = 0,
    source: str = "",
) -> bool:
    """Apply a regex replacement in a file. Returns True if changes were made."""
    if not filepath.exists():
        return False
    content = filepath.read_text()
    new_content = re.sub(pattern, replacement, content, flags=flags)
    if new_content == content:
        return False
    record_changes(filepath, content, new_content, source or pattern)
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
        if replace_in_file(
            f,
            pattern,
            replacement,
            dry_run,
            flags=handler.flags,
            source=handler.name,
        ):
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
        # Start-of-line anchored: only the top-level `[project] version` key
        # sits in column 0. Without the anchor this also matches suffixed keys
        # (`target-version = "..."`) and any nested/inline-table `version = `
        # belonging to a third-party pin.
        pattern=r'(^version\s*=\s*")OLD(")',
        replacement=r"\g<1>NEW\2",
        version_format="pep440",
        flags=re.MULTILINE,
    ),
    Handler(
        name="Python Packages (__init__.py __version__)",
        globs=[
            "src/runtime/python/_mcp_mesh/__init__.py",
            "src/runtime/python/mesh/__init__.py",
        ],
        # Start-of-line anchored: the module-level dunder, not a `__version__`
        # read off some other package inside a function body.
        pattern=r'(^__version__\s*=\s*")OLD(")',
        replacement=r"\g<1>NEW\2",
        version_format="pep440",
        flags=re.MULTILINE,
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
        # Anchored to the top-level key (column 0 plus one indent level).
        # Nested `"version"` keys — e.g. the `"scripts": { "version": "napi
        # version" }` entry in src/runtime/core/typescript/package.json — are
        # deeper and are not ours to rewrite.
        pattern=r'(^ {0,2}"version":\s*")OLD(")',
        replacement=r"\g<1>NEW\2",
        flags=re.MULTILINE,
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
        # Start-of-line anchored: the `[package] version` key. Every crate we
        # depend on declares its pin as an inline table
        # (`pyo3 = { version = "0.27", ... }`), which the unanchored form
        # would happily rewrite the day a crate's version collides with ours.
        pattern=r'(^version\s*=\s*")OLD(")',
        replacement=r"\g<1>NEW\2",
        flags=re.MULTILINE,
    ),
    # --- Category 9: Package Managers (Homebrew + Scoop) ------------------
    Handler(
        name="Package Managers (Homebrew)",
        globs=["packaging/homebrew/mcp-mesh.rb"],
        # Anchored to the formula-body indent. A Homebrew formula can carry
        # `resource "..." do ... version "..." end` blocks for third-party
        # dependencies; those nest deeper than the formula's own version.
        pattern=r'(^  version\s+")OLD(")',
        replacement=r"\g<1>NEW\2",
        flags=re.MULTILINE,
    ),
    Handler(
        name="Package Managers (Scoop)",
        globs=["packaging/scoop/mcp-mesh.json"],
        # Anchored to the top-level key; a Scoop manifest's `architecture`
        # and `checkver` blocks nest deeper.
        pattern=r'(^ {0,2}"version":\s*")OLD(")',
        replacement=r"\g<1>NEW\2",
        flags=re.MULTILINE,
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
    # The embedded pom.xml template also pins spring-boot-starter-parent, so a
    # blind `<version>OLD</version>` here is the same trap that broke the 3.3.1
    # Java publish (#1379). Anchored to the io.mcp-mesh coordinate.
    Handler(
        name="Go Handler Templates (java_handler.go <version>)",
        globs=["src/core/cli/handlers/java_handler.go"],
        pattern=(
            r"(<groupId>io\.mcp-mesh</groupId>\s*"
            r"<artifactId>[^<]+</artifactId>\s*<version>)OLD(</version>)"
        ),
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
    #
    # All three are deliberately left unanchored — there is no mesh token on
    # the same line to anchor to. `--version X` sits on its own backslash
    # continuation line of a `helm upgrade ... mcp-mesh/<chart>` command;
    # `<version>X</version>` is one line below the artifactId; `vX` is bare
    # prose. Narrowing them to the same line would stop legitimate sites from
    # updating. The over-match guard covers these instead: it reads the
    # surrounding lines, so the mesh coordinate one line up still counts.
    Handler(
        name="Documentation (--version OLD)",
        globs=[
            "docs/**/*.md",
            "src/core/cli/man/content/**/*.md",
        ],
        pattern=r"(--version\s+)OLD",
        replacement=r"\g<1>NEW",
    ),
    # Anchored to the io.mcp-mesh coordinate, exactly like the POM handler.
    # These docs quote whole POMs, third-party pins included:
    # spring-boot-starter-parent sits at <version>4.0.2</version> in six of
    # them, so the blind form was #1379's twin waiting for mesh to reach 4.0.2.
    # The reader's OWN project version in those listings is deliberately not
    # matched — a tutorial app's version is not ours to bump.
    Handler(
        name="Documentation (<version>OLD</version>)",
        globs=[
            "docs/**/*.md",
            "src/core/cli/man/content/**/*.md",
        ],
        pattern=(
            r"(<groupId>io\.mcp-mesh</groupId>\s*"
            r"<artifactId>[^<]+</artifactId>\s*<version>)OLD(</version>)"
        ),
        replacement=r"\g<1>NEW\2",
    ),
    Handler(
        name="Documentation (vOLD)",
        globs=[
            "docs/**/*.md",
            "src/core/cli/man/content/**/*.md",
        ],
        # Word boundary; not preceded by `/` so URLs aren't touched, and not
        # preceded by `:` so a docker tag isn't either. A tag like
        # `your-registry/my-agent:vX` belongs to the READER's image — the `/`
        # guard missed it because the colon sits between.
        pattern=r"(?<![/:])vOLD(?=[\s,\)\]\"']|$)",
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
    # Both are the `workflow_dispatch` version input (its default, and the
    # example inside its description). A YAML input default carries no
    # artifact name, so there is nothing to anchor to; both globs are single
    # files and the sites are on the over-match allowlist.
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
    # `--version X` again sits on a continuation line of a `helm upgrade`
    # command whose chart ref is on the preceding line — left unanchored for
    # the same reason as the documentation handler.
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
    # Dockerfile templates use full version tags (mcpmesh/python-runtime:1.3.0).
    # This used to replace `[^\s]+` — whatever tag was there, whether or not it
    # was OLD. That silently clobbers any deliberately different tag (a pinned
    # older runtime, `:latest`, a build-arg), which is a distinct failure mode
    # from the over-match class and one the over-match guard cannot flag: the
    # line does name a mesh image, so it reads as ours. Now OLD-matching like
    # every other handler; a template left behind is caught by coverage_guard,
    # which already scans for a surviving `mcpmesh/<image>:OLD`.
    Handler(
        name="Docker Image Tags (Scaffold Dockerfile.tmpl)",
        globs=["cmd/meshctl/templates/*/*/Dockerfile.tmpl"],
        pattern=(
            r"(mcpmesh/(?:python-runtime|typescript-runtime"
            r"|java-runtime):)OLD(?![\d.\-+])"
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
        if replace_in_file(
            chart_yaml,
            p1,
            rf"\g<1>{new}",
            dry_run,
            flags=re.MULTILINE,
            source="Helm Charts (chart version)",
        ):
            file_changed = True
        # appVersion: "OLD"
        p2 = rf'(appVersion:\s*"){re.escape(old)}(")'
        if replace_in_file(
            chart_yaml,
            p2,
            rf"\g<1>{new}\2",
            dry_run,
            source="Helm Charts (appVersion)",
        ):
            file_changed = True
        # dependency version: "OLD" (indented, in dependencies section)
        p3 = rf'(    version:\s*"){re.escape(old)}(")'
        if replace_in_file(
            chart_yaml,
            p3,
            rf"\g<1>{new}\2",
            dry_run,
            source="Helm Charts (dependency version)",
        ):
            file_changed = True
        if file_changed:
            changed.append(str(chart_yaml.relative_to(PROJECT_ROOT)))

    # Chart.lock file
    chart_lock = helm_dir / "mcp-mesh-core" / "Chart.lock"
    if chart_lock.exists():
        pattern = rf"(  version:\s*){re.escape(old)}$"
        if replace_in_file(
            chart_lock,
            pattern,
            rf"\g<1>{new}",
            dry_run,
            flags=re.MULTILINE,
            source="Helm Charts (Chart.lock)",
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
                if replace_in_file(
                    values_yaml,
                    pattern,
                    replacement,
                    dry_run,
                    source="Helm Charts (values.yaml image tag)",
                ):
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
        record_changes(f, content, new_content, "Test Config")
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
            record_changes(f, content, new_content, "Test Documentation")
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


def _guard_multiline_patterns(old: str) -> list[re.Pattern]:
    """Mesh-shaped contexts that genuinely span several lines.

    The Maven coordinate — ``<groupId>io.mcp-mesh</groupId>`` /
    ``<artifactId>…</artifactId>`` / ``<version>OLD</version>`` — is three
    lines, so the per-line scan in `coverage_guard` can never see it. Three
    handlers now anchor on exactly this shape (the Java POM handler, the
    documentation ``<version>`` handler and the java_handler.go template), so
    without this pass a pattern of theirs that is too tight would skip a real
    site with nothing to catch it — the false negative the guard exists for.

    Each pattern puts the version itself in a group named ``hit`` so the
    reported line number points at the ``<version>`` line rather than the
    ``<groupId>`` line the match starts on.
    """
    o = re.escape(old)
    return [
        re.compile(
            r"<groupId>io\.mcp-mesh</groupId>\s*"
            r"<artifactId>[^<]+</artifactId>\s*"
            r"(?P<hit><version>" + o + r"</version>)"
        ),
    ]


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
    ml_patterns = _guard_multiline_patterns(old)
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
        lines = text.splitlines()
        flagged: set[int] = set()
        for lineno, line in enumerate(lines, start=1):
            if any(tok in line for tok in _GUARD_ALLOWLIST_TOKENS):
                continue
            if any(p.search(line) for p in patterns):
                survivors.append(f"{rel}:{lineno}: {line.strip()}")
                flagged.add(lineno)
        # Second pass over the whole file text for the multi-line shapes,
        # reporting the line the version itself sits on and skipping anything
        # the per-line pass already flagged.
        for p in ml_patterns:
            for m in p.finditer(text):
                lineno = text.count("\n", 0, m.start("hit")) + 1
                if lineno in flagged or lineno > len(lines):
                    continue
                line = lines[lineno - 1]
                if any(tok in line for tok in _GUARD_ALLOWLIST_TOKENS):
                    continue
                survivors.append(f"{rel}:{lineno}: {line.strip()}")
                flagged.add(lineno)
    return (True, survivors)


# ---------------------------------------------------------------------------
# Post-bump over-match guard
# ---------------------------------------------------------------------------
#
# `coverage_guard` answers "did we MISS a mesh version?" — false negatives.
# This guard answers the opposite question, which is where both shipped
# incidents came from: "did we rewrite something that isn't ours?"
#
#   - #1379 (v3.3.1): the Java POM handler's blind `<version>OLD</version>`
#     bumped maven-jar-plugin 3.3.0 -> a nonexistent 3.3.1 and broke the Java
#     publish after PyPI/npm/crates had already gone out.
#   - #1388 (v0.9.1): `typer>=0.9.0` -> `>=0.9.1`, unnoticed for five years.
#
# The rule: every line we rewrote must be PROVABLY mcp-mesh-owned. Anchoring
# individual patterns shrinks the surface; only this guard proves nothing
# foreign changed — including for handlers added later.

# A mesh identifier anywhere in the line or its immediate neighbourhood is
# proof of ownership. Covers mcp-mesh, mcp_mesh, mcpmesh, "MCP Mesh" (docs
# prose), io.mcp-mesh (Maven), @mcpmesh/ (npm) and tsuite-mesh (test images).
_MESH_TOKEN = re.compile(r"mcp[-_ ]?mesh|tsuite[-_ ]?mesh", re.IGNORECASE)

# How many lines either side of a changed line count as "immediate context".
# Three is what makes an XML `<artifactId>…</artifactId>` / `<version>` pair
# and a JSON `"name"` / `"version"` pair resolvable, without loosening the
# guard enough to absorb an unrelated neighbouring block.
_CONTEXT_RADIUS = 3

# NOTE: "the file path names a mesh artifact" is deliberately NOT accepted as
# proof. It would clear src/runtime/java/mcp-mesh-native/pom.xml wholesale —
# the exact file #1379 damaged — and empirically it only clears lines the
# allowlist below already covers with a stated reason.


@dataclass(frozen=True)
class Exemption:
    """A (file glob, line pattern) pair allowed to change without carrying a
    mesh identifier, plus why it cannot be proven any other way.

    Entries are intentionally narrow — a blanket path allowlist would defeat
    the guard. `pattern`, and the optional `context` (matched against the same
    ±_CONTEXT_RADIUS window as the mesh-token check), may use `NEW` as a
    placeholder for the new version in any of its projections.
    """

    glob: str
    pattern: str
    reason: str
    context: str = ""


# Seeded from a 3.3.1 -> 9.9.9 sentinel bump: 455 files / 660 changed lines
# reduce to 25 lines that no rule can prove, every one of them legitimate.
OVERMATCH_ALLOWLIST: list[Exemption] = [
    Exemption(
        glob=".github/workflows/*release.yml",
        pattern=r'default:\s*"vNEW"',
        reason=(
            "workflow_dispatch version input default. A YAML input default is "
            "a bare scalar — there is no artifact name on the line or near it "
            "to anchor to, and adding one would change the input contract."
        ),
    ),
    Exemption(
        glob=".github/workflows/*release.yml",
        pattern=r'description:\s*"[^"]*e\.g\.,?\s*vNEW',
        reason="the example version inside that same input's description.",
    ),
    Exemption(
        glob="docs/index.md",
        pattern=r"\*\*Latest Release\*\*:\s*vNEW",
        reason=(
            "the release line on the docs landing page; the sentence names "
            "the release, not an artifact."
        ),
    ),
    Exemption(
        glob="docs/concepts/stateful-agents.md",
        pattern=r"\bvNEW\b",
        reason=(
            "narrative prose ('Since vX, lifespan and all tool bodies share "
            "one loop') dating a runtime behavior change. The document is "
            "about the mesh runtime, but these two sentences carry no "
            "coordinate. Scoped to this one file so a bare vX anywhere else "
            "in docs/ is still challenged."
        ),
    ),
    # NOTE: the three sites that used to live here — the tutorial POM's own
    # <version> in docs/java/getting-started/index.md and quickstart_java.md,
    # and `your-registry/my-agent:vX` in the deployment man pages — were not
    # exemptions worth keeping. They are the READER's version, not ours, and
    # only tracked our release because the patterns were loose. The docs now
    # pin them to a neutral 1.0.0 and the patterns no longer match them.
    Exemption(
        glob="src/runtime/python/mesh/__init__.py",
        pattern=r'^__version__\s*=\s*"NEW"',
        reason=(
            "the mesh package's own __version__ constant. The distribution is "
            "mcp-mesh but the import package is `mesh`, so neither the line "
            "nor its neighbours spell the mesh name."
        ),
    ),
    Exemption(
        glob="src/runtime/python/_mcp_mesh/__init__.py",
        pattern=r'^__version__\s*=\s*"NEW"',
        reason=(
            "same constant in the private runtime package; here the mesh "
            "token is in the directory name only, which is not proof."
        ),
    ),
    Exemption(
        glob="tests/lib-tests/config.yaml",
        pattern=r'^\s*(?:cli|core|sdk_python|sdk_typescript|sdk_java)_version:\s*"NEW"',
        reason=(
            "tsuite package-version block. The keys name each artifact by "
            "role (cli/core/sdk_*) rather than by coordinate, and the block "
            "is dense enough that no surrounding key names the mesh."
        ),
    ),
    Exemption(
        glob="tests/lib-tests/README.md",
        pattern=r'^\s*(?:cli|core|sdk_python|sdk_typescript|sdk_java)_version:\s*"NEW"',
        reason="the same block quoted verbatim in the suite README.",
    ),
    Exemption(
        glob="tests/integration/suites/README.md",
        pattern=r"`config\.packages\.[a-z_]*version`\s*\|\s*NEW\s*\|",
        reason="the same keys again, as rows of a markdown reference table.",
    ),
]


def _version_alternation(new: str) -> str:
    """Regex alternation over every projection of the new version, so an
    allowlist pattern can say `NEW` without caring whether the site carries
    the raw, PEP 440 or minor form."""
    forms = {new, to_pep440(new), to_minor(new)}
    ordered = sorted(forms, key=len, reverse=True)
    return "(?:" + "|".join(re.escape(f) for f in ordered) + ")"


def _expand_new(pattern: str, new: str) -> str:
    return pattern.replace("NEW", _version_alternation(new))


def overmatch_guard(new: str) -> list[ChangedLine]:
    """Return every recorded change that is not provably mcp-mesh-owned.

    A change is proven when the rewritten line carries a mesh identifier, when
    its immediate context does, or when an explicit `OVERMATCH_ALLOWLIST`
    entry covers the (file, line) pair. Anything else is a suspect: either a
    handler over-matched a third-party pin, or a new legitimate site needs an
    allowlist entry that justifies itself.

    Reads the in-memory change log rather than `git diff`, so it is correct on
    a dirty tree and under --dry-run.
    """
    exemptions = [
        (
            _glob_to_regex(e.glob),
            re.compile(_expand_new(e.pattern, new), re.MULTILINE),
            re.compile(_expand_new(e.context, new)) if e.context else None,
        )
        for e in OVERMATCH_ALLOWLIST
    ]

    suspects: list[ChangedLine] = []
    seen: set[tuple[str, int]] = set()
    for change in _CHANGE_LOG:
        key = (change.path, change.lineno)
        if key in seen:
            continue
        seen.add(key)

        if _MESH_TOKEN.search(change.text):
            continue

        lines = change.snapshot
        lo = max(0, change.lineno - 1 - _CONTEXT_RADIUS)
        hi = min(len(lines), change.lineno + _CONTEXT_RADIUS)
        window = "\n".join(lines[lo:hi])
        if _MESH_TOKEN.search(window):
            continue

        if any(
            glob_re.match(change.path)
            and line_re.search(change.text)
            and (ctx_re is None or ctx_re.search(window))
            for glob_re, line_re, ctx_re in exemptions
        ):
            continue

        suspects.append(change)

    return sorted(suspects, key=lambda c: (c.path, c.lineno))


def changed_line_count() -> int:
    return len({(c.path, c.lineno) for c in _CHANGE_LOG})


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
    reset_change_log()
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

    failed = False

    # Over-match guard: every line we rewrote must be provably mesh-owned.
    # Runs under --dry-run too — the change log is populated either way, so
    # suspects surface before anything is written.
    suspects = overmatch_guard(new)
    print()
    if suspects:
        failed = True
        print(
            f"❌ Over-match guard: {len(suspects)} of {changed_line_count()} "
            "changed line(s) are not provably mcp-mesh-owned:"
        )
        for s in suspects:
            print(f"  {s.path}:{s.lineno}: {s.text.strip()}")
            print(f"      rewritten by handler: {s.source}")
        print(
            "None of these carry an mcp-mesh identifier on the line or within "
            f"{_CONTEXT_RADIUS} lines of it, and none are covered by "
            "OVERMATCH_ALLOWLIST in scripts/bump_version.py."
        )
        print(
            "Either a handler over-matched a third-party pin that happens to "
            f"sit at {old} (anchor its pattern to a mesh coordinate), or the "
            "site is legitimate (add a narrow OVERMATCH_ALLOWLIST entry "
            "saying why it cannot be proven)."
        )
        if not dry_run:
            print(
                "Files have already been written — run 'git checkout -- .' "
                "before retrying."
            )
    else:
        print(
            f"✅ Over-match guard: all {changed_line_count()} changed lines "
            "are provably mcp-mesh-owned."
        )

    # Verify no mesh-shaped reference to the OLD version survived. Skipped on
    # --dry-run (nothing was written, so every ref would "survive").
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
            failed = True
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
        else:
            print(
                f"✅ Coverage guard: no stale mesh-shaped references to {old} "
                "remain."
            )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
