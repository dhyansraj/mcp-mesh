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


def test_pip_requirement_needs_a_whole_version_token():
    """OLD must be the whole version, never a prefix of a longer one: without
    a terminal boundary the guard reads `==2.8.00` as a stale `2.8.0`. Letters
    count too — `2.8.0rc1` is a different version under PEP 440, and no
    handler would rewrite it, so flagging it is a survivor nobody can clear."""
    old = "2.8.0"
    assert not _matches(old, "mcp-mesh[litellm]==2.8.00")
    assert not _matches(old, "mcp-mesh[litellm]==2.8.0rc1")
    assert not _matches(old, "mcp-mesh==2.8.0.post1")
    # The same widened boundary is shared with the image-tag, npm and
    # --version patterns; they must not regress on the exact form either.
    assert not _matches(old, "FROM mcpmesh/cli:2.8.0rc1")
    assert not _matches(old, "helm upgrade --version 2.8.0rc1")
    assert _matches(old, "FROM mcpmesh/cli:2.8.0")
    assert _matches(old, "helm upgrade --version 2.8.0")


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


def test_coverage_guard_catches_a_frozen_release_coordinate():
    """#1405 gave the matcher the power to VETO a rewrite, which converts a
    loud failure (a doc reads the wrong version) into a silent one (a
    coordinate quietly stops tracking). An over-broad PROVENANCE_PROSE entry
    would leave the docs landing page advertising the previous release while
    the bump completes and both guards print green.

    None of the other guard patterns matches a bare `vX` in prose, so this one
    is the only thing standing between an over-veto and a bad release."""
    old = "3.3.1"
    assert _matches(old, "- **Latest Release**: v3.3.1")
    assert _matches(old, "- **Latest Release**: 3.3.1")  # `v` optional
    # ...and it clears once the bump has actually landed.
    assert not _matches(old, "- **Latest Release**: v3.3.2")
    # Whole-version token only: a longer version is not a stale 3.3.1.
    assert not _matches(old, "- **Latest Release**: v3.3.10")
    assert not _matches(old, "- **Latest Release**: v3.3.1rc1")


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
    #
    # It is also why the guard is structurally blind to #1405: this exact line
    # is a corrupted provenance claim (it read v1.0.0 when written), yet it
    # clears, correctly, because the line really is about mesh. Ownership is
    # not the question a dated claim raises. Only the matcher can answer it,
    # which is why PROVENANCE_PROSE exists and no exemption was added.
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
            line_excludes=handler.line_excludes,
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
        "Install MCP Mesh v3.3.1 to get started\n"
        "see https://example.com/v3.3.1 for details\n"
    )
    assert _apply_handler("Documentation (vOLD)", text) == (
        "docker buildx build -t your-registry/my-agent:v3.3.1 --push .\n"
        "Install MCP Mesh v3.4.0 to get started\n"  # undated prose still moves
        "see https://example.com/v3.3.1 for details\n"  # URL still skipped
    )


def test_docs_v_prefix_handler_leaves_provenance_prose_alone():
    """#1405. A sentence that DATES a behaviour states when it shipped — a
    historical fact, not a coordinate. Bumping it is always wrong, and it
    ratchets: four such sentences walked forward on every release for eight
    releases, one of them since v1.0.0, until they claimed a v2.2.4 behaviour
    had landed in whatever release was being cut."""
    text = (
        "Since v3.3.1, tool dispatch runs on a single-user loop.\n"
        "Because v3.3.1 runs your lifespan on the user loop, this works.\n"
        "### Matching semantics (as of v3.3.1)\n"
        "Prior to v3.3.1, all entries used prefix matching.\n"
        "The channel shipped in v3.3.1 and has not changed.\n"
        "MCP Mesh v3.3.1 adds a media pipeline.\n"
        "This was introduced in v3.3.1 and refined later.\n"
        "Available since v3.3.1 on every runtime.\n"
        "Starting with v3.3.1, the default flipped.\n"
    )
    assert _apply_handler("Documentation (vOLD)", text) == text


def test_provenance_lead_in_tolerates_the_spellings_our_docs_use():
    """The lead-in list is only useful if it matches how the docs are actually
    written. `Since MCP Mesh vX` is the spelling docs/concepts/architecture.md
    uses, and that file carried the longest-running corruption of the four —
    a bare `\\s+v?\\d` lead-in would have kept right on ratcheting it.

    The `<verb> in` entries mirror the trailing verb list: the two forms are
    the same claim with the version on the other side of the verb, so a verb
    covered in one direction and not the other is an arbitrary hole."""
    text = (
        # Filler between the lead-in and the version.
        "Since MCP Mesh v3.3.1, tools share one loop.\n"
        "Since mcp-mesh v3.3.1, tools share one loop.\n"
        "As of the v3.3.1 release, this is the default.\n"
        "Since the v3.3.1 release, this is the default.\n"
        # Lead-in verbs mirrored from the trailing list.
        "The flag was removed in v3.3.1 and has no replacement.\n"
        "The flag was deprecated in v3.3.1.\n"
        "The default was changed in v3.3.1.\n"
        "The leak was fixed in v3.3.1.\n"
        "The feature was released in v3.3.1.\n"
        "The env var was renamed in v3.3.1.\n"
        # Availability window.
        "Supported in v3.3.1 and later on every runtime.\n"
        "Supported in v3.3.1 or newer on every runtime.\n"
        "Available from v3.3.1 onwards.\n"
        # Hyphenated relative form (docs/environment-variables.md:421).
        "# revert to pre-v3.3.1 immediate cancel-forward\n"
        "This is post-v3.3.1 behaviour.\n"
    )
    assert _apply_handler("Documentation (vOLD)", text) == text


def test_provenance_covers_parenthesised_version_labels():
    """A version in parentheses labels WHICH release a heading, example or
    column applies to — provenance in heading form.

    The bare parenthetical is the genuinely exposed shape: `)` and `,` are
    both in the handler's trailing character class. It is live today at
    src/core/cli/man/content/headers.md:51 and :62, safe only because those
    versions are historical. (An earlier `vX+` plus-suffix pattern could never
    fire at all — `+` falls outside that class, so `(v3.3.1+)` never produced
    a match to suppress.)"""
    text = (
        "### Migration note (v3.3.1 → v3.4.9)\n"
        "# Before (v3.3.1):                    After (v3.4.9, pick one):\n"
        "## Loop topology (v3.3.1+)\n"
        "**Tag-Level OR** (v3.3.1+):\n"
        "### Matching semantics (v3.3.1)\n"
    )
    assert _apply_handler("Documentation (vOLD)", text) == text
    # The arrow's right-hand side has no preceding paren of its own, so the
    # arrow rule is what protects it — check it in isolation.
    assert (
        _apply_handler("Documentation (vOLD)", "upgrade path v2.2.4 -> v3.3.1\n")
        == "upgrade path v2.2.4 -> v3.3.1\n"
    )


def test_docs_v_prefix_handler_still_bumps_the_release_coordinate():
    """The inverse risk, and the reason the exclusion tests overlap with the
    matched version rather than the whole line: an over-broad rule would
    silently freeze a genuine coordinate, and the docs landing page's
    `**Latest Release**` line is exactly that — it names the CURRENT release
    and must track every bump."""
    assert _apply_handler(
        "Documentation (vOLD)", "- **Latest Release**: v3.3.1\n"
    ) == "- **Latest Release**: v3.4.0\n"
    # Mixed line: the dated claim is pinned, the coordinate beside it is not.
    assert _apply_handler(
        "Documentation (vOLD)",
        "Since v2.2.4 this is the default; upgrade to v3.3.1 to get it.\n",
    ) == "Since v2.2.4 this is the default; upgrade to v3.4.0 to get it.\n"
    # A dated claim naming the version being bumped is still pinned, even
    # though the two versions are then identical.
    assert _apply_handler(
        "Documentation (vOLD)",
        "Since v3.3.1 this is the default; upgrade to v3.3.1 to get it.\n",
    ) == "Since v3.3.1 this is the default; upgrade to v3.4.0 to get it.\n"


def test_provenance_exclusion_is_wired_to_the_prose_handler():
    """The exclusion only works if it is actually attached. `Documentation
    (vOLD)` is the sole handler that rewrites a bare version in running prose,
    so it is the sole handler that can corrupt a dated claim — if a refactor
    drops `line_excludes` from it, the ratchet silently resumes."""
    handler = {h.name: h for h in bv.HANDLERS}["Documentation (vOLD)"]
    assert handler.line_excludes is bv.PROVENANCE_PROSE
    assert "docs/**/*.md" in handler.globs
    assert "src/core/cli/man/content/**/*.md" in handler.globs


def test_no_exemption_covers_bare_prose_versions():
    """#1395 exempted `\\bvNEW\\b` in docs/concepts/stateful-agents.md, which
    told the guard to stop reporting a rewrite that was itself wrong. An
    exemption is only ever right when the rewrite is CORRECT but unprovable;
    reaching for one to quiet a genuine mis-rewrite is what let #1405 run for
    eight releases."""
    for e in bv.OVERMATCH_ALLOWLIST:
        anchor = _literal_anchor(e.pattern)
        assert anchor not in ("v", ""), (
            f"{e.glob}: pattern {e.pattern!r} exempts any bare prose version. "
            "If a bare vX is being rewritten wrongly, fix the matcher "
            "(PROVENANCE_PROSE), not the guard."
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


def test_scaffold_requirements_litellm_extra_is_not_prefix_matched():
    """Terminal boundary: a 3.3.1 -> 3.3.2 bump used to rewrite the PREFIX of
    a longer pin, turning `==3.3.10` into the nonexistent `==3.3.20`."""
    text = "mcp-mesh[litellm]==3.3.10\nmcp-mesh[litellm]==3.3.1rc1\n"
    assert (
        _apply_handler(
            "Scaffold Templates (Python requirements.txt.tmpl litellm extra)",
            text,
            old="3.3.1",
            new="3.3.2",
        )
        == text
    )


def test_pip_pin_handlers_are_not_prefix_matched():
    """The three sibling pip-pin handlers carried the same unbounded prefix
    match: each must leave a longer version alone, and still bump its own."""
    cases = [
        ("Go Handler Templates (python_handler.go pip dep)", "mcp-mesh>="),
        ("Go Handler Templates (language_test.go pip dep)", "mcp-mesh=="),
        ("Example Requirements (requirements.txt)", "mcp-mesh>="),
    ]
    for name, prefix in cases:
        skipped = f"{prefix}3.3.10\n{prefix}3.3.1rc1\n"
        assert _apply_handler(name, skipped, old="3.3.1", new="3.3.2") == skipped, name
        # The boundary must not over-block: the genuine pin still moves.
        assert (
            _apply_handler(name, f"{prefix}3.3.1\n", old="3.3.1", new="3.3.2")
            == f"{prefix}3.3.2\n"
        ), name


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


# Characters that can legally continue a PEP 440 version. `3.3.1` followed by
# any of these is a DIFFERENT version (`3.3.10`, `3.3.1rc1`, `3.3.1.post1`,
# `3.3.1-1`, `3.3.1+local`), never a stale copy of ours.
_VERSION_CONTINUATION = "0123456789abcrpostABC_.-+"


def _version_continuations_admitted(pattern: str) -> list[str]:
    """Which continuation characters the pattern would still let follow OLD.

    Everything after the OLD placeholder is the terminal boundary, so compile
    that tail on its own and ask it to match each continuation character. A
    boundary that is doing its job cannot match one: `(?![\\w.\\-+])` fails the
    lookahead, and a literal delimiter like `(")` or `(</version>)` fails on the
    first character. A pattern with no boundary at all leaves an EMPTY tail,
    which matches zero-width against anything — so every character comes back,
    which is exactly the prefix over-match this list is here to forbid."""
    tail = pattern.split("OLD", 1)[1]
    compiled = re.compile(tail)
    return [c for c in _VERSION_CONTINUATION if compiled.match(c)]


def test_every_handler_terminally_bounds_the_version():
    """EVERY handler must terminate its version match.

    The pip-pin handlers carry `(?![\\w.\\-+])` because someone remembered to
    add it after `==3.3.10` was rewritten into the nonexistent `==3.3.20`;
    others end at a closing quote or `</version>`, which bounds it just as
    well. Both are fine — what must not happen is a NEW handler, or a refactor
    of an old one, that ends the pattern at OLD and re-opens prefix matching.
    Nothing else notices: the handler still bumps our pin correctly, and the
    corruption only appears in whichever release first sits next to a longer
    version.

    #1409 widened this from pep440-only to every handler, and that immediately
    found three `raw` handlers that ended at OLD with no boundary at all —
    `--version OLD` (docs and the docker-example helm values) and
    `e.g., vOLD` (the release workflows). Every site in the tree carries the
    exact version today, so nothing was corrupted; the exposure was identical
    to the pip pins' and had simply never been looked for, because the scope
    line in this test said not to look.

    The pep440/raw split the old scope rested on does not survive contact: a
    version's continuation characters are a property of versions, not of which
    projection a handler substitutes."""
    offenders = {}
    for h in bv.HANDLERS:
        admitted = _version_continuations_admitted(h.pattern)
        if admitted:
            offenders[h.name] = (h.pattern, admitted)
    assert not offenders, (
        "handler(s) match a PREFIX of a longer version — add the terminal "
        "boundary `(?![\\w.\\-+])` after OLD (or end the pattern at a "
        f"delimiter that cannot appear in a version): {offenders}"
    )


def test_image_tag_handlers_use_the_wide_boundary():
    """#1427/#1409: the guard and the handlers must agree on what our version
    is.

    The image-tag handlers carried `(?![\\d.\\-+])`, which admits LETTERS, so a
    3.3.1 bump would have rewritten `mcpmesh/cli:3.3.1rc1`. The coverage guard
    has always used `(?![\\w.\\-+])` and therefore ignored that exact tag —
    which is asserted directly by
    `test_pip_requirement_needs_a_whole_version_token`. Guard and handler
    disagreed about whether `3.3.1rc1` is ours.

    The guard is right. A letter-suffixed tag is a different version, and there
    is no rewrite of one a bump could get right: `3.3.1rc1` -> `3.3.2rc1` names
    a release candidate that may never exist. The handlers now use the wide
    form, so a tag the guard ignores is a tag the handler leaves alone."""
    narrow = r"(?![\d.\-+])"
    offenders = [h.name for h in bv.HANDLERS if h.pattern.endswith("OLD" + narrow)]
    assert not offenders, (
        "handler(s) still use the digits-only boundary, which admits letters "
        "and so rewrites versions the coverage guard does not consider ours: "
        f"{offenders}"
    )


def test_image_tag_handler_leaves_a_letter_suffixed_tag_alone():
    """The behavioural half of the assertion above, on the exact tag
    test_pip_requirement_needs_a_whole_version_token pins the guard against."""
    text = (
        "FROM mcpmesh/python-runtime:3.3.1\n"
        "FROM mcpmesh/python-runtime:3.3.1rc1\n"
        "FROM mcpmesh/python-runtime:3.3.10\n"
    )
    assert _apply_handler(
        "Docker Image Tags in Dockerfiles", text, old="3.3.1", new="3.3.2"
    ) == (
        "FROM mcpmesh/python-runtime:3.3.2\n"
        "FROM mcpmesh/python-runtime:3.3.1rc1\n"
        "FROM mcpmesh/python-runtime:3.3.10\n"
    )
    # ...and the guard agrees the two skipped tags are not stale copies of ours.
    assert not _matches("3.3.1", "FROM mcpmesh/python-runtime:3.3.1rc1")
    assert not _matches("3.3.1", "FROM mcpmesh/python-runtime:3.3.10")
    assert _matches("3.3.1", "FROM mcpmesh/python-runtime:3.3.1")


def test_version_flag_handlers_are_not_prefix_matched():
    """The three handlers #1409 found unbounded. `--version 3.3.10` must not be
    read as a `3.3.1` that needs bumping to `3.3.20`."""
    for name in (
        "Documentation (--version OLD)",
        "Docker Example Helm Values",
    ):
        skipped = "  --version 3.3.10 \\\n  --version 3.3.1rc1 \\\n"
        assert _apply_handler(name, skipped, old="3.3.1", new="3.3.2") == skipped, name
        assert (
            _apply_handler(name, "  --version 3.3.1 \\\n", old="3.3.1", new="3.3.2")
            == "  --version 3.3.2 \\\n"
        ), name

    ci = 'description: "Version to release (e.g., v3.3.10)"\n'
    assert _apply_handler(
        "CI/CD Workflows (e.g., vOLD)", ci, old="3.3.1", new="3.3.2"
    ) == ci
    assert _apply_handler(
        "CI/CD Workflows (e.g., vOLD)",
        'description: "Version to release (e.g., v3.3.1)"\n',
        old="3.3.1",
        new="3.3.2",
    ) == 'description: "Version to release (e.g., v3.3.2)"\n'


def test_terminal_boundary_check_bites():
    """The check above is only worth having if it goes red when the boundary
    goes away, so exercise it against the shapes it exists to reject: no
    boundary at all, and a boundary narrowed until it stops covering the
    alphabetic suffixes PEP 440 allows (and the letter-suffixed docker tags the
    same narrowing let through)."""
    real = r"(mcp-mesh\[litellm\]==)OLD(?![\w.\-+])"
    assert _version_continuations_admitted(real) == []

    for broken, why in [
        (r"(mcp-mesh\[litellm\]==)OLD", "boundary deleted"),
        (r"(mcp-mesh\[litellm\]==)OLD(?!\d)", "digits only"),
        (r"(mcp-mesh\[litellm\]==)OLD(?![\d.\-+])", "the old image-tag boundary"),
        (r"(mcp-mesh\[litellm\]==)OLD(\d*)", "a trailing wildcard"),
    ]:
        assert _version_continuations_admitted(broken), why

    # ...and the whole-handler assertion must fail with such a handler present,
    # not just the helper. Probed in BOTH projections, because the check no
    # longer filters on version_format and a regression that reintroduced the
    # filter would still pass a pep440-only probe.
    original = list(bv.HANDLERS)
    for fmt, pattern in (
        ("pep440", r"(mcp-mesh>=)OLD"),
        ("raw", r"(mcpmesh/registry:)OLD"),
        ("raw", r"(mcpmesh/registry:)OLD(?![\d.\-+])"),
    ):
        try:
            bv.HANDLERS.append(
                bv.Handler(
                    name=f"unbounded probe ({fmt}: {pattern})",
                    globs=["does/not/exist"],
                    pattern=pattern,
                    replacement=r"\g<1>NEW",
                    version_format=fmt,
                )
            )
            try:
                test_every_handler_terminally_bounds_the_version()
            except AssertionError:
                pass
            else:
                raise AssertionError(
                    "the boundary check accepted a handler with no terminal "
                    f"boundary: {pattern}"
                )
        finally:
            bv.HANDLERS[:] = original


def test_boundary_check_bites_on_the_narrow_image_tag_form():
    """`(?![\\d.\\-+])` is not "no boundary" — it stops digits and dots, so the
    `3.3.10` case is covered. It is specifically the LETTERS it admits, which
    is what test_image_tag_handlers_use_the_wide_boundary forbids by shape and
    this exercises through the check itself."""
    admitted = _version_continuations_admitted(r"(mcpmesh/cli:)OLD(?![\d.\-+])")
    assert admitted, "the narrow boundary admits nothing?"
    assert all(c.isalpha() or c == "_" for c in admitted), admitted

    original = list(bv.HANDLERS)
    try:
        bv.HANDLERS.append(
            bv.Handler(
                name="narrow probe",
                globs=["does/not/exist"],
                pattern=r"(mcpmesh/cli:)OLD(?![\d.\-+])",
                replacement=r"\g<1>NEW",
            )
        )
        try:
            test_image_tag_handlers_use_the_wide_boundary()
        except AssertionError:
            pass
        else:
            raise AssertionError(
                "the wide-boundary check accepted a digits-only boundary"
            )
    finally:
        bv.HANDLERS[:] = original


def test_cargo_lock_reminder_is_the_targeted_command():
    """#1407: the reminder said `cargo generate-lockfile`, which re-resolves the
    ENTIRE dependency graph rather than refreshing our own version. Operators
    followed it, so v3.2.3 and v3.3.1 each shipped six third-party crate moves
    — including the napi chain and cc, which rebuild the native module — under
    notes claiming no runtime change. Neither guard can see that: both only
    inspect lines carrying the mesh version.

    The string IS the release checklist for this step, so it is worth pinning
    like one."""
    source = (bv.PROJECT_ROOT / "scripts" / "bump_version.py").read_text()
    # The reminder block, not this test's own prose or the explanatory comment.
    reminders = [
        line
        for line in source.splitlines()
        if "cargo" in line and not line.lstrip().startswith("#")
    ]
    joined = "\n".join(reminders)
    assert "cargo update --package mcp-mesh-core" in joined, joined
    assert "Do NOT run 'cargo generate-lockfile'" in joined, joined
    assert "check_release_lockfiles.py" in source


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed")
