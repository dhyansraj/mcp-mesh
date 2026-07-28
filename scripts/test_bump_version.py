#!/usr/bin/env python3
"""Lightweight checks for scripts/bump_version.py's two guards.

Run directly (`python scripts/test_bump_version.py`) or via pytest. These
exercise `_guard_patterns` against representative lines so a future edit that
breaks mesh-shaped detection (like the @mcpmesh package.json form that the
first cut of the guard silently missed) fails loudly, and exercise
`overmatch_guard` so the opposite direction — rewriting a third-party pin
that happens to sit at our version — cannot regress either.
"""

import importlib.util
import pathlib
import re
import tempfile

_spec = importlib.util.spec_from_file_location(
    "bump_version", pathlib.Path(__file__).with_name("bump_version.py")
)
bv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bv)


def _matches(old: str, line: str, new: str | None = None) -> bool:
    return any(p.search(line) for p in bv._guard_patterns(old, new))


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


def test_patch_bump_leaves_minor_tag():
    # The minor image tag (tag: "2.8") intentionally tracks the latest patch,
    # so a patch bump must NOT flag it as stale (to_minor unchanged)...
    assert not _matches("2.8.0", '  tag: "2.8"', new="2.8.1")
    # ...but a minor/major bump still catches it, and the full tag always does.
    assert _matches("2.8.0", '  tag: "2.8"', new="2.9.0")
    assert _matches("2.8.0", '  tag: "2.8.0"', new="2.8.1")


def test_non_mesh_lines_ignored():
    old = "2.8.0"
    assert not _matches(old, '        "node": ">=12.8.0"')      # engines range
    assert not _matches(old, 'version = "2.8.0"  # crate')      # third-party
    assert not _matches(old, "FROM mcpmesh/python-runtime:2.8.01")  # boundary


def _guard_on(rel_path: str, before: str, after: str, new: str = "3.3.1"):
    """Feed one file's before/after through the change recorder and return the
    over-match guard's verdict for it."""
    bv.reset_change_log()
    bv.record_changes(bv.PROJECT_ROOT / rel_path, before, after, "test handler")
    return bv.overmatch_guard(new)


def test_overmatch_guard_flags_third_party_pin():
    # The #1379 shape: a plugin pinned at the mesh version, no mesh token on
    # the line or anywhere near it.
    pom = """<build>
    <plugins>
        <plugin>
            <groupId>org.apache.maven.plugins</groupId>
            <artifactId>maven-jar-plugin</artifactId>
            <version>{v}</version>
        </plugin>
    </plugins>
</build>
"""
    suspects = _guard_on(
        "src/runtime/java/mcp-mesh-native/pom.xml",
        pom.format(v="3.3.0"),
        pom.format(v="3.3.1"),
    )
    assert len(suspects) == 1, suspects
    assert suspects[0].lineno == 6
    assert "maven-jar-plugin" not in suspects[0].text  # it names the version line
    assert suspects[0].text.strip() == "<version>3.3.1</version>"


def test_overmatch_guard_clears_mesh_coordinate():
    # Same shape, but the artifactId two lines up is ours -> proven by context.
    pom = """<dependency>
    <groupId>io.mcp-mesh</groupId>
    <artifactId>mcp-mesh-spring-boot-starter</artifactId>
    <version>{v}</version>
</dependency>
"""
    assert not _guard_on(
        "src/runtime/java/mcp-mesh-native/pom.xml",
        pom.format(v="3.3.0"),
        pom.format(v="3.3.1"),
    )


def test_overmatch_guard_clears_line_level_token():
    assert not _guard_on(
        "docs/index.md",
        "docker pull mcpmesh/registry:3.3.0\n",
        "docker pull mcpmesh/registry:3.3.1\n",
    )
    # Prose form: "MCP Mesh v3.3.1 adds ..." — the space-separated spelling
    # counts, which is what keeps narrative docs out of the report.
    assert not _guard_on(
        "docs/concepts/architecture.md",
        "MCP Mesh v3.3.0 adds a media pipeline\n",
        "MCP Mesh v3.3.1 adds a media pipeline\n",
    )


def test_overmatch_guard_path_is_not_proof():
    # A mesh-named path must NOT clear a foreign line: mcp-mesh-native/pom.xml
    # is exactly the file #1379 damaged.
    suspects = _guard_on(
        "src/runtime/java/mcp-mesh-native/pom.xml",
        "<version>3.3.0</version>\n",
        "<version>3.3.1</version>\n",
    )
    assert len(suspects) == 1, suspects


def test_overmatch_allowlist_entries_are_narrow():
    # Every exemption must state a reason and must not be a bare path pass.
    for e in bv.OVERMATCH_ALLOWLIST:
        assert e.reason.strip(), e
        assert e.pattern not in ("", ".*", "NEW"), e


def _apply_handler(name: str, text: str, old="3.3.1", new="3.4.0") -> str:
    """Run one named handler's regex over `text` and return the result."""
    handler = {h.name: h for h in bv.HANDLERS}[name]
    old_v = bv.format_version(old, handler.version_format)
    new_v = bv.format_version(new, handler.version_format)
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "sample"
        f.write_text(text)
        bv.reset_change_log()
        bv.replace_in_file(
            f,
            handler.pattern.replace("OLD", re.escape(old_v)),
            handler.replacement.replace("NEW", new_v),
            dry_run=False,
            flags=handler.flags,
        )
        return f.read_text()


def test_docs_version_handler_skips_third_party_maven_pin():
    """docs/ quote whole POMs. spring-boot-starter-parent is pinned 4.0.2 in
    six of them, so the blind <version>OLD</version> form was #1379's twin
    waiting for mesh to reach 4.0.2 — mesh is on a 3.x -> 4.x trajectory."""
    pom = """    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.3.1</version>
    </parent>

    <groupId>com.example</groupId>
    <artifactId>greeter-agent</artifactId>
    <version>3.3.1</version>

    <dependencies>
        <dependency>
            <groupId>io.mcp-mesh</groupId>
            <artifactId>mcp-mesh-spring-boot-starter</artifactId>
            <version>{starter}</version>
        </dependency>
    </dependencies>
"""
    out = _apply_handler("Documentation (<version>OLD</version>)",
                         pom.format(starter="3.3.1"))
    # Only the io.mcp-mesh dependency moves; Spring Boot's pin and the
    # reader's own project version are left exactly where they were.
    assert out == pom.format(starter="3.4.0"), out


def test_overmatch_guard_would_catch_a_loosened_docs_version_handler():
    """If the anchoring above were ever reverted, the guard must surface the
    Spring Boot line — no mesh identifier on it or within 3 lines."""
    before = """    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>4.0.2</version>
    </parent>
"""
    suspects = _guard_on(
        "docs/java/getting-started/index.md",
        before,
        before.replace("4.0.2", "4.0.3"),
        new="4.0.3",
    )
    assert len(suspects) == 1, suspects
    assert suspects[0].text.strip() == "<version>4.0.3</version>"


def test_docs_v_prefix_handler_skips_docker_tags():
    """`(?<!/)` did not stop `your-registry/my-agent:v3.3.1` — the colon sits
    between the slash and the v. That tag is the READER's image."""
    text = (
        "docker buildx build -t your-registry/my-agent:v3.3.1 --push .\n"
        "MCP Mesh v3.3.1 adds a media pipeline\n"
        "see https://example.com/v3.3.1 for details\n"
    )
    assert _apply_handler("Documentation (vOLD)", text) == (
        "docker buildx build -t your-registry/my-agent:v3.3.1 --push .\n"
        "MCP Mesh v3.4.0 adds a media pipeline\n"  # prose still updates
        "see https://example.com/v3.3.1 for details\n"  # URL still skipped
    )


def test_scaffold_dockerfile_handler_matches_old_only():
    """Used to replace `[^\\s]+` — any tag, whether or not it was OLD, which
    silently clobbers a deliberately different pin."""
    text = (
        "FROM mcpmesh/python-runtime:3.3.1\n"
        "FROM mcpmesh/java-runtime:latest\n"
        "FROM mcpmesh/typescript-runtime:${RUNTIME_TAG}\n"
    )
    assert _apply_handler("Docker Image Tags (Scaffold Dockerfile.tmpl)", text) == (
        "FROM mcpmesh/python-runtime:3.4.0\n"
        "FROM mcpmesh/java-runtime:latest\n"
        "FROM mcpmesh/typescript-runtime:${RUNTIME_TAG}\n"
    )


def test_anchored_patterns_skip_third_party_pins():
    """The anchored handlers must leave an inline/nested third-party pin that
    collides with our version alone, while still bumping our own field."""
    cases = [
        (
            "Rust Cargo.toml",
            "Cargo.toml",
            '[package]\nversion = "3.3.1"\n\n[dependencies]\n'
            'pyo3 = { version = "3.3.1" }\n',
            '[package]\nversion = "3.4.0"\n\n[dependencies]\n'
            'pyo3 = { version = "3.3.1" }\n',
        ),
        (
            "Python Packages (pyproject.toml)",
            "pyproject.toml",
            '[project]\nversion = "3.3.1"\n\n[tool.black]\n'
            'target-version = "3.3.1"\n',
            '[project]\nversion = "3.4.0"\n\n[tool.black]\n'
            'target-version = "3.3.1"\n',
        ),
        (
            "TypeScript/Node.js Packages",
            "package.json",
            '{\n  "version": "3.3.1",\n  "scripts": {\n'
            '    "version": "3.3.1"\n  }\n}\n',
            '{\n  "version": "3.4.0",\n  "scripts": {\n'
            '    "version": "3.3.1"\n  }\n}\n',
        ),
    ]
    handlers = {h.name: h for h in bv.HANDLERS}
    for name, filename, before, expected in cases:
        handler = handlers[name]
        pattern = handler.pattern.replace("OLD", "3\\.3\\.1")
        replacement = handler.replacement.replace("NEW", "3.4.0")
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / filename
            f.write_text(before)
            bv.reset_change_log()
            bv.replace_in_file(f, pattern, replacement, dry_run=False,
                               flags=handler.flags)
            assert f.read_text() == expected, f"{name}: got\n{f.read_text()}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed")
