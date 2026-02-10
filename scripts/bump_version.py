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
"""

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


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


def bump_python_packages(
    old: str, new_pep440: str, dry_run: bool
) -> list[str]:
    """Category 1: Python package version fields."""
    changed = []
    files = [
        PROJECT_ROOT / "packaging" / "pypi" / "pyproject.toml",
        PROJECT_ROOT / "src" / "runtime" / "python" / "pyproject.toml",
        PROJECT_ROOT / "src" / "runtime" / "core" / "pyproject.toml",
    ]
    old_pep440 = to_pep440(old)
    for f in files:
        pattern = rf'(version\s*=\s*"){re.escape(old_pep440)}(")'
        replacement = rf"\g<1>{new_pep440}\2"
        if replace_in_file(f, pattern, replacement, dry_run):
            changed.append(str(f.relative_to(PROJECT_ROOT)))

    init_file = (
        PROJECT_ROOT / "src" / "runtime" / "python" / "_mcp_mesh" / "__init__.py"
    )
    pattern = rf'(__version__\s*=\s*"){re.escape(old_pep440)}(")'
    replacement = rf"\g<1>{new_pep440}\2"
    if replace_in_file(init_file, pattern, replacement, dry_run):
        changed.append(str(init_file.relative_to(PROJECT_ROOT)))

    return changed


def bump_python_dependencies(
    old: str, new_pep440: str, dry_run: bool
) -> list[str]:
    """Category 2: Python OUR dependencies (mcp-mesh-core only)."""
    changed = []
    f = PROJECT_ROOT / "packaging" / "pypi" / "pyproject.toml"
    old_pep440 = to_pep440(old)
    pattern = rf'("mcp-mesh-core>={re.escape(old_pep440)}")'
    replacement = f'"mcp-mesh-core>={new_pep440}"'
    if replace_in_file(f, pattern, replacement, dry_run):
        changed.append(str(f.relative_to(PROJECT_ROOT)) + " (mcp-mesh-core dep)")
    return changed


def bump_typescript_packages(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 3: TypeScript/Node.js core package versions."""
    changed = []
    files = [
        PROJECT_ROOT / "src" / "runtime" / "typescript" / "package.json",
        PROJECT_ROOT / "src" / "runtime" / "core" / "typescript" / "package.json",
        PROJECT_ROOT / "npm" / "cli" / "package.json",
    ]
    for f in files:
        pattern = rf'("version":\s*"){re.escape(old)}(")'
        replacement = rf"\g<1>{new}\2"
        if replace_in_file(f, pattern, replacement, dry_run):
            changed.append(str(f.relative_to(PROJECT_ROOT)))
    return changed


def bump_typescript_dependencies(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 4: @mcpmesh/* dependency versions in package.json files."""
    changed = []
    files = [
        PROJECT_ROOT / "npm" / "cli" / "package.json",
        PROJECT_ROOT / "src" / "runtime" / "typescript" / "package.json",
    ]
    for f in files:
        # Match "@mcpmesh/anything": "OLD" or "@mcpmesh/anything": "^OLD"
        pattern = rf'("@mcpmesh/[^"]+?":\s*")(\^?){re.escape(old)}(")'
        replacement = rf"\g<1>\g<2>{new}\3"
        if replace_in_file(f, pattern, replacement, dry_run):
            changed.append(str(f.relative_to(PROJECT_ROOT)))
    return changed


def bump_java_parent_poms(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 5: Java parent/module POM versions."""
    changed = []
    files = [
        PROJECT_ROOT / "src" / "runtime" / "java" / "pom.xml",
        PROJECT_ROOT / "src" / "runtime" / "java" / "mcp-mesh-bom" / "pom.xml",
        PROJECT_ROOT / "src" / "runtime" / "java" / "mcp-mesh-core" / "pom.xml",
        PROJECT_ROOT / "src" / "runtime" / "java" / "mcp-mesh-sdk" / "pom.xml",
        PROJECT_ROOT
        / "src"
        / "runtime"
        / "java"
        / "mcp-mesh-spring-boot-starter"
        / "pom.xml",
        PROJECT_ROOT / "src" / "runtime" / "java" / "mcp-mesh-spring-ai" / "pom.xml",
        PROJECT_ROOT / "src" / "runtime" / "java" / "mcp-mesh-native" / "pom.xml",
    ]
    for f in files:
        pattern = rf"(<version>){re.escape(old)}(</version>)"
        replacement = rf"\g<1>{new}\2"
        if replace_in_file(f, pattern, replacement, dry_run):
            changed.append(str(f.relative_to(PROJECT_ROOT)))
    return changed


def bump_java_example_poms(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 6: Java example POM mcp-mesh.version property."""
    changed = []
    # Find all example pom.xml files
    patterns = [
        PROJECT_ROOT / "examples" / "java",
        PROJECT_ROOT / "examples" / "toolcalls",
    ]
    pom_files = []
    for base_dir in patterns:
        if base_dir.exists():
            for pom in base_dir.glob("*/pom.xml"):
                pom_files.append(pom)

    for f in pom_files:
        pattern = (
            rf"(<mcp-mesh\.version>){re.escape(old)}(</mcp-mesh\.version>)"
        )
        replacement = rf"\g<1>{new}\2"
        if replace_in_file(f, pattern, replacement, dry_run):
            changed.append(str(f.relative_to(PROJECT_ROOT)))
    return changed


def bump_rust_cargo(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 7: Rust Cargo.toml version."""
    changed = []
    f = PROJECT_ROOT / "src" / "runtime" / "core" / "Cargo.toml"
    pattern = rf'(version\s*=\s*"){re.escape(old)}(")'
    replacement = rf"\g<1>{new}\2"
    if replace_in_file(f, pattern, replacement, dry_run):
        changed.append(str(f.relative_to(PROJECT_ROOT)))
    return changed


def bump_helm_charts(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 8: Helm Chart.yaml and Chart.lock files."""
    changed = []
    helm_dir = PROJECT_ROOT / "helm"
    if not helm_dir.exists():
        return changed

    # Chart.yaml files
    for chart_yaml in helm_dir.glob("*/Chart.yaml"):
        file_changed = False
        # version: OLD (top-level chart version, start of line)
        p1 = rf"(^version:\s*){re.escape(old)}$"
        if replace_in_file(
            chart_yaml, p1, rf"\g<1>{new}", dry_run, flags=re.MULTILINE
        ):
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
    return changed


def bump_package_managers(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 9: Homebrew and Scoop package manager files."""
    changed = []

    # Homebrew
    homebrew = PROJECT_ROOT / "packaging" / "homebrew" / "mcp-mesh.rb"
    pattern = rf'(version\s+"){re.escape(old)}(")'
    replacement = rf"\g<1>{new}\2"
    if replace_in_file(homebrew, pattern, replacement, dry_run):
        changed.append(str(homebrew.relative_to(PROJECT_ROOT)))

    # Scoop
    scoop = PROJECT_ROOT / "packaging" / "scoop" / "mcp-mesh.json"
    pattern = rf'("version":\s*"){re.escape(old)}(")'
    replacement = rf"\g<1>{new}\2"
    if replace_in_file(scoop, pattern, replacement, dry_run):
        changed.append(str(scoop.relative_to(PROJECT_ROOT)))

    return changed


def bump_go_handler_templates(
    old: str, new: str, new_pep440: str, dry_run: bool
) -> list[str]:
    """Category 10: Go handler template files."""
    changed = []
    handlers_dir = PROJECT_ROOT / "src" / "core" / "cli" / "handlers"

    # python_handler.go: mcp-mesh>=OLD
    f = handlers_dir / "python_handler.go"
    old_pep440 = to_pep440(old)
    pattern = rf"(mcp-mesh>={re.escape(old_pep440)})"
    replacement = f"mcp-mesh>={new_pep440}"
    if replace_in_file(f, pattern, replacement, dry_run):
        changed.append(str(f.relative_to(PROJECT_ROOT)))

    # typescript_handler.go: "@mcpmesh/sdk": "^OLD"
    f = handlers_dir / "typescript_handler.go"
    pattern = rf'("@mcpmesh/sdk":\s*"\^){re.escape(old)}(")'
    replacement = rf"\g<1>{new}\2"
    if replace_in_file(f, pattern, replacement, dry_run):
        changed.append(str(f.relative_to(PROJECT_ROOT)))

    # java_handler.go: <version>OLD</version>
    f = handlers_dir / "java_handler.go"
    pattern = rf"(<version>){re.escape(old)}(</version>)"
    replacement = rf"\g<1>{new}\2"
    if replace_in_file(f, pattern, replacement, dry_run):
        changed.append(str(f.relative_to(PROJECT_ROOT)))

    # language_test.go: mcp-mesh==OLD
    f = handlers_dir / "language_test.go"
    pattern = rf"(mcp-mesh=={re.escape(old_pep440)})"
    replacement = f"mcp-mesh=={new_pep440}"
    if replace_in_file(f, pattern, replacement, dry_run):
        changed.append(str(f.relative_to(PROJECT_ROOT)))

    return changed


def bump_scaffold_templates(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 11: Scaffold template files (meshctl scaffold)."""
    changed = []
    templates_dir = PROJECT_ROOT / "cmd" / "meshctl" / "templates"

    # Java templates: <mcp-mesh.version>OLD</mcp-mesh.version>
    for pom_tmpl in sorted(templates_dir.glob("java/*/pom.xml.tmpl")):
        pattern = (
            rf"(<mcp-mesh\.version>){re.escape(old)}(</mcp-mesh\.version>)"
        )
        replacement = rf"\g<1>{new}\2"
        if replace_in_file(pom_tmpl, pattern, replacement, dry_run):
            changed.append(str(pom_tmpl.relative_to(PROJECT_ROOT)))

    # TypeScript templates: "@mcpmesh/sdk": "^OLD"
    for pkg_tmpl in sorted(templates_dir.glob("typescript/*/package.json.tmpl")):
        pattern = rf'("@mcpmesh/sdk":\s*"\^){re.escape(old)}(")'
        replacement = rf"\g<1>{new}\2"
        if replace_in_file(pkg_tmpl, pattern, replacement, dry_run):
            changed.append(str(pkg_tmpl.relative_to(PROJECT_ROOT)))

    return changed


def _bump_version_in_md(
    md_file: Path, old: str, new: str, dry_run: bool
) -> bool:
    """Apply version replacement patterns to a single markdown file."""
    file_changed = False

    # --version OLD -> --version NEW
    p1 = rf"(--version\s+){re.escape(old)}"
    if replace_in_file(md_file, p1, rf"\g<1>{new}", dry_run):
        file_changed = True

    # <version>OLD</version> -> <version>NEW</version>
    p2 = rf"(<version>){re.escape(old)}(</version>)"
    if replace_in_file(md_file, p2, rf"\g<1>{new}\2", dry_run):
        file_changed = True

    # vOLD in version strings (word boundary, not preceded by / to avoid URLs)
    p4 = rf"(?<!/)v{re.escape(old)}(?=[\s,\)\]\"']|$)"
    if replace_in_file(md_file, p4, f"v{new}", dry_run, flags=re.MULTILINE):
        file_changed = True

    return file_changed


def bump_documentation(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 12: Documentation markdown files."""
    changed = []

    md_dirs = [
        PROJECT_ROOT / "docs",
        PROJECT_ROOT / "src" / "core" / "cli" / "man" / "content",
    ]

    for md_dir in md_dirs:
        if not md_dir.exists():
            continue
        for md_file in md_dir.rglob("*.md"):
            if _bump_version_in_md(md_file, old, new, dry_run):
                changed.append(str(md_file.relative_to(PROJECT_ROOT)))

    return changed


def bump_test_config(
    old: str, new: str, new_pep440: str, dry_run: bool
) -> list[str]:
    """Category 13: Test configuration file."""
    changed = []
    f = PROJECT_ROOT / "tests" / "lib-tests" / "config.yaml"
    if not f.exists():
        return changed

    content = f.read_text()
    old_pep440 = to_pep440(old)
    new_content = content

    # Replace non-Python version lines
    for key in ["cli_version", "sdk_typescript_version", "core_version", "sdk_java_version"]:
        p = rf'({key}:\s*"){re.escape(old)}(")'
        new_content = re.sub(p, rf"\g<1>{new}\2", new_content)

    # sdk_python_version uses PEP 440 format
    p = rf'(sdk_python_version:\s*"){re.escape(old_pep440)}(")'
    new_content = re.sub(p, rf"\g<1>{new_pep440}\2", new_content)

    if new_content != content:
        if not dry_run:
            f.write_text(new_content)
        changed.append(str(f.relative_to(PROJECT_ROOT)))

    return changed


def bump_example_requirements(
    old: str, new_pep440: str, dry_run: bool
) -> list[str]:
    """Category 14: Example agent requirements.txt files."""
    changed = []
    agents_dir = PROJECT_ROOT / "examples" / "docker-examples" / "agents"
    if not agents_dir.exists():
        return changed

    old_pep440 = to_pep440(old)
    for req_file in agents_dir.glob("*/requirements.txt"):
        pattern = rf"(mcp-mesh>={re.escape(old_pep440)})"
        replacement = f"mcp-mesh>={new_pep440}"
        if replace_in_file(req_file, pattern, replacement, dry_run):
            changed.append(str(req_file.relative_to(PROJECT_ROOT)))
    return changed


def bump_ts_toolcall_examples(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 16: TypeScript toolcall example package.json files."""
    changed = []
    toolcalls_dir = PROJECT_ROOT / "examples" / "toolcalls"
    if not toolcalls_dir.exists():
        return changed

    for pkg in sorted(toolcalls_dir.glob("*-ts/package.json")):
        # Match "@mcpmesh/anything": "OLD" or "@mcpmesh/anything": "^OLD"
        pattern = rf'("@mcpmesh/[^"]+?":\s*")\^?{re.escape(old)}(")'
        replacement = rf"\g<1>^{new}\2"
        if replace_in_file(pkg, pattern, replacement, dry_run):
            changed.append(str(pkg.relative_to(PROJECT_ROOT)))
    return changed


def bump_docker_example_helm(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 17: Docker example Helm values files."""
    changed = []
    agents_dir = PROJECT_ROOT / "examples" / "docker-examples" / "agents"
    if not agents_dir.exists():
        return changed

    for helm_file in sorted(agents_dir.glob("*/helm-values.yaml")):
        pattern = rf"(--version\s+){re.escape(old)}"
        replacement = rf"\g<1>{new}"
        if replace_in_file(helm_file, pattern, replacement, dry_run):
            changed.append(str(helm_file.relative_to(PROJECT_ROOT)))
    return changed


def bump_integration_test_artifacts(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 18: Integration test TypeScript artifact package.json files."""
    changed = []
    suites_dir = PROJECT_ROOT / "tests" / "integration" / "suites"
    if not suites_dir.exists():
        return changed

    for pkg in sorted(suites_dir.rglob("*/package.json")):
        # Match "@mcpmesh/sdk": "OLD" or "@mcpmesh/sdk": "^OLD"
        pattern = rf'("@mcpmesh/[^"]+?":\s*")(\^?){re.escape(old)}(")'
        replacement = rf"\g<1>\g<2>{new}\3"
        if replace_in_file(pkg, pattern, replacement, dry_run):
            changed.append(str(pkg.relative_to(PROJECT_ROOT)))
    return changed


def bump_test_documentation(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 19: Test documentation README files."""
    changed = []
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


def bump_ci_workflows(old: str, new: str, dry_run: bool) -> list[str]:
    """Category 15: CI/CD workflow files."""
    changed = []
    workflows = [
        PROJECT_ROOT / ".github" / "workflows" / "release.yml",
        PROJECT_ROOT / ".github" / "workflows" / "helm-release.yml",
    ]
    for f in workflows:
        if not f.exists():
            continue
        file_changed = False

        # default: "vOLD" -> default: "vNEW"
        p1 = rf'(default:\s*"v){re.escape(old)}(")'
        if replace_in_file(f, p1, rf"\g<1>{new}\2", dry_run):
            file_changed = True

        # e.g., vOLD -> e.g., vNEW
        p2 = rf"(e\.g\.,\s*v){re.escape(old)}"
        if replace_in_file(f, p2, rf"\g<1>{new}", dry_run):
            file_changed = True

        if file_changed:
            changed.append(str(f.relative_to(PROJECT_ROOT)))
    return changed


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

    categories: list[tuple[str, list[str]]] = []

    # Category 1: Python Packages
    changed = bump_python_packages(old, new_pep440, dry_run)
    categories.append(("Python Packages", changed))

    # Category 2: Python Dependencies
    changed = bump_python_dependencies(old, new_pep440, dry_run)
    categories.append(("Python Dependencies", changed))

    # Category 3: TypeScript/Node.js Packages
    changed = bump_typescript_packages(old, new, dry_run)
    categories.append(("TypeScript/Node.js Packages", changed))

    # Category 4: TypeScript Dependencies
    changed = bump_typescript_dependencies(old, new, dry_run)
    categories.append(("TypeScript Dependencies", changed))

    # Category 5: Java Parent/Module POMs
    changed = bump_java_parent_poms(old, new, dry_run)
    categories.append(("Java Parent/Module POMs", changed))

    # Category 6: Java Example POMs
    changed = bump_java_example_poms(old, new, dry_run)
    categories.append(("Java Example POMs", changed))

    # Category 7: Rust Cargo.toml
    changed = bump_rust_cargo(old, new, dry_run)
    categories.append(("Rust Cargo.toml", changed))

    # Category 8: Helm Charts
    changed = bump_helm_charts(old, new, dry_run)
    categories.append(("Helm Charts", changed))

    # Category 9: Package Managers
    changed = bump_package_managers(old, new, dry_run)
    categories.append(("Package Managers", changed))

    # Category 10: Go Handler Templates
    changed = bump_go_handler_templates(old, new, new_pep440, dry_run)
    categories.append(("Go Handler Templates", changed))

    # Category 11: Scaffold Templates
    changed = bump_scaffold_templates(old, new, dry_run)
    categories.append(("Scaffold Templates", changed))

    # Category 12: Documentation
    changed = bump_documentation(old, new, dry_run)
    categories.append(("Documentation", changed))

    # Category 13: Test Config
    changed = bump_test_config(old, new, new_pep440, dry_run)
    categories.append(("Test Config", changed))

    # Category 14: Example Requirements
    changed = bump_example_requirements(old, new_pep440, dry_run)
    categories.append(("Example Requirements", changed))

    # Category 15: CI/CD Workflows
    changed = bump_ci_workflows(old, new, dry_run)
    categories.append(("CI/CD Workflows", changed))

    # Category 16: TypeScript Toolcall Examples
    changed = bump_ts_toolcall_examples(old, new, dry_run)
    categories.append(("TypeScript Toolcall Examples", changed))

    # Category 17: Docker Example Helm Values
    changed = bump_docker_example_helm(old, new, dry_run)
    categories.append(("Docker Example Helm Values", changed))

    # Category 18: Integration Test Artifacts
    changed = bump_integration_test_artifacts(old, new, dry_run)
    categories.append(("Integration Test Artifacts", changed))

    # Category 19: Test Documentation
    changed = bump_test_documentation(old, new, dry_run)
    categories.append(("Test Documentation", changed))

    # Print results
    total_files = 0
    total_categories = 0
    for name, files in categories:
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

    # Summary
    if dry_run:
        print(
            f"[DRY RUN] Would update {total_files} files across "
            f"{total_categories} categories"
        )
    else:
        print(f"Summary: {total_files} files updated across {total_categories} categories")

    # Reminder for Helm Chart.lock
    chart_lock = PROJECT_ROOT / "helm" / "mcp-mesh-core" / "Chart.lock"
    if chart_lock.exists():
        print()
        print(
            "Reminder: run 'helm dependency update helm/mcp-mesh-core' "
            "to regenerate Chart.lock digest"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
