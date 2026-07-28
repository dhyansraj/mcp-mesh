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


def test_pip_requirement_with_extras():
    """`mcp-mesh[litellm]==X` (#1383) is a pip requirement like any other —
    the bracketed extras sit between the name and the specifier, which the
    first cut of this pattern read straight past."""
    old = "2.8.0"
    assert _matches(old, "mcp-mesh[litellm]==2.8.0")
    assert _matches(old, "pip install 'mcp-mesh[litellm]==2.8.0'")
    assert _matches(old, "mcp-mesh[litellm,vertex]>=2.8.0")
    assert _matches(old, "mcp-mesh==2.8.0")  # bare form still matches


def _matches_multiline(old: str, text: str) -> bool:
    return any(p.search(text) for p in bv._guard_multiline_patterns(old))


def test_maven_coordinate_guard_needs_the_whole_text():
    """Three handlers anchor on the io.mcp-mesh groupId/artifactId/version
    coordinate. It spans three lines, so a per-line scan can never see it —
    the guard must match against the full file text."""
    old = "3.3.1"
    coord = """        <dependency>
            <groupId>{g}</groupId>
            <artifactId>mcp-mesh-spring-boot-starter</artifactId>
            <version>{v}</version>
        </dependency>
"""
    assert not _matches(old, "            <version>3.3.1</version>")
    assert _matches_multiline(old, coord.format(g="io.mcp-mesh", v="3.3.1"))
    assert not _matches_multiline(old, coord.format(g="io.mcp-mesh", v="3.4.0"))
    # A third-party coordinate parked at our version is not a missed bump.
    assert not _matches_multiline(
        old, coord.format(g="org.springframework.boot", v="3.3.1")
    )


def test_maven_coordinate_guard_reports_the_version_line():
    """The match starts on <groupId>, but the survivor must be reported at the
    <version> line — same offset arithmetic coverage_guard uses."""
    text = (
        "<dependencies>\n"
        "    <groupId>io.mcp-mesh</groupId>\n"
        "    <artifactId>mcp-mesh-sdk</artifactId>\n"
        "    <version>3.3.1</version>\n"
    )
    m = bv._guard_multiline_patterns("3.3.1")[0].search(text)
    assert m
    assert text.count("\n", 0, m.start("hit")) + 1 == 4


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


def test_changed_line_keeps_its_own_snapshot():
    """11 file patterns are touched by more than one handler (docs/**/*.md by
    four). A record must be windowed against the content it was recorded
    against, so a later handler that shifts line numbers cannot silently move
    an earlier record's neighbourhood."""
    f = bv.PROJECT_ROOT / "docs/guide.md"
    first_before = "intro\nintro\n<version>3.3.0</version>\nio.mcp-mesh\nend\nend\n"
    first_after = first_before.replace("3.3.0", "3.3.1")
    # Second handler deletes the mesh line, shifting everything below it up.
    second_after = first_after.replace("io.mcp-mesh\n", "")

    bv.reset_change_log()
    bv.record_changes(f, first_before, first_after, "handler one")
    assert len(bv._CHANGE_LOG) == 1
    assert bv._CHANGE_LOG[0].lineno == 3
    assert bv._CHANGE_LOG[0].snapshot == first_after.splitlines()

    bv.record_changes(f, first_after, second_after, "handler two")
    # Pure deletion: nothing new recorded, and the first record still owns its
    # own snapshot rather than the shorter, mesh-free one.
    assert len(bv._CHANGE_LOG) == 1
    assert bv._CHANGE_LOG[0].snapshot == first_after.splitlines()
    # ...so it is still proven by the io.mcp-mesh line that sat next to it.
    assert not bv.overmatch_guard("3.3.1")
    # Sanity: that proof really did come from the pre-deletion neighbourhood.
    assert "mcp-mesh" not in second_after


def _literal_anchor(pattern: str) -> str:
    """The literal characters an allowlist pattern is tied to: the NEW
    placeholder, regex metacharacters, escape classes (\\s, \\b) and character
    classes all removed. What is left is real text from the actual construct.
    A pattern that reduces to '' matches by shape alone (`.+`, `NEW.*`, ...)
    and is therefore a blanket pass for its glob."""
    out: list[str] = []
    p = pattern.replace("NEW", "\x00")
    i = 0
    while i < len(p):
        c = p[i]
        if c == "\\" and i + 1 < len(p):
            # \. \" \, -> a literal character; \s \b \d -> a class, not literal
            if not p[i + 1].isalnum():
                out.append(p[i + 1])
            i += 2
        elif c == "[":  # character class: matches a set, anchors nothing
            close = p.find("]", i + 1)
            i = len(p) if close == -1 else close + 1
        elif c in ".*+?^$(){}|\x00":
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out).strip()


def test_overmatch_allowlist_entries_are_narrow():
    """An exemption suppresses the guard, so each one must be pinned to a
    specific file AND to specific literal text. Anything that passes by shape
    alone (`**` + `.+`, `NEW.*`, ...) reopens the hole the guard closes."""
    for e in bv.OVERMATCH_ALLOWLIST:
        assert e.reason.strip(), f"{e.glob}: exemptions must state a reason"

        # Glob: must name something. A pure-wildcard glob is a path pass.
        assert set(e.glob) - set("*/?"), f"{e.glob}: glob matches everything"
        assert e.glob not in ("", "*", "**", "*/*", "**/*", "**/**"), (
            f"{e.glob}: glob matches everything"
        )

        # Pattern: must carry literal text beyond the NEW placeholder.
        anchor = _literal_anchor(e.pattern)
        assert anchor, (
            f"{e.glob}: pattern {e.pattern!r} has no literal anchor — it "
            "exempts any changed line carrying the new version"
        )


def test_overmatch_allowlist_narrowness_check_rejects_broad_entries():
    """The narrowness check itself must bite: each of these would sail past
    the old `pattern not in ('', '.*', 'NEW')` assertion."""
    broad = [
        bv.Exemption(glob="**", pattern=".+", reason="r"),
        bv.Exemption(glob="docs/index.md", pattern="NEW.*", reason="r"),
        bv.Exemption(glob="docs/index.md", pattern=".*NEW.*", reason="r"),
        bv.Exemption(glob="**/*", pattern=r"\bvNEW\b", reason="r"),
        bv.Exemption(glob="docs/index.md", pattern=r"\s*NEW\s*", reason="r"),
    ]
    original = list(bv.OVERMATCH_ALLOWLIST)
    try:
        for e in broad:
            bv.OVERMATCH_ALLOWLIST[:] = original + [e]
            try:
                test_overmatch_allowlist_entries_are_narrow()
            except AssertionError:
                continue
            raise AssertionError(f"narrowness check accepted broad entry: {e}")
    finally:
        bv.OVERMATCH_ALLOWLIST[:] = original


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


def test_scaffold_requirements_litellm_extra_handler():
    """The generated requirements.txt pins the optional LiteLLM extra (#1383).
    Only OUR pin moves — a user's third-party pin sitting at the same version
    is not ours to bump."""
    text = (
        "# my-provider dependencies\n"
        "mcp-mesh[litellm]==3.3.1\n"
        "some-vendor-sdk==3.3.1\n"
    )
    assert _apply_handler(
        "Scaffold Templates (Python requirements.txt.tmpl litellm extra)", text
    ) == (
        "# my-provider dependencies\n"
        "mcp-mesh[litellm]==3.4.0\n"
        "some-vendor-sdk==3.3.1\n"
    )


def test_anchored_patterns_skip_third_party_pins():
    """The anchored handlers must leave an inline/nested third-party pin that
    collides with our version alone, while still bumping our own field."""
    cases = [
        (
            "Rust Cargo.toml",
            '[package]\nversion = "3.3.1"\n\n[dependencies]\n'
            'pyo3 = { version = "3.3.1" }\n',
            '[package]\nversion = "3.4.0"\n\n[dependencies]\n'
            'pyo3 = { version = "3.3.1" }\n',
        ),
        (
            "Python Packages (pyproject.toml)",
            '[project]\nversion = "3.3.1"\n\n[tool.black]\n'
            'target-version = "3.3.1"\n',
            '[project]\nversion = "3.4.0"\n\n[tool.black]\n'
            'target-version = "3.3.1"\n',
        ),
        (
            "TypeScript/Node.js Packages",
            '{\n  "version": "3.3.1",\n  "scripts": {\n'
            '    "version": "3.3.1"\n  }\n}\n',
            '{\n  "version": "3.4.0",\n  "scripts": {\n'
            '    "version": "3.3.1"\n  }\n}\n',
        ),
    ]
    for name, before, expected in cases:
        out = _apply_handler(name, before)
        assert out == expected, f"{name}: got\n{out}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed")
