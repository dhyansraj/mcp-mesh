#!/usr/bin/env python3
"""Checks for scripts/check_doc_claims.py (#1500).

The point of these is not that the checker runs. It is that the two failures
that motivated it -- both of which stayed green through review, CI and a
release -- go RED when replayed. A doc-claim guard that has only ever been
seen passing is indistinguishable from one that matches nothing, which is
exactly the state the man corpus tests were in when #1499 shipped.

So the two central tests carry the historical prose verbatim, taken from the
commits that removed it:

  #1499 -- 6f2c07039^ `health_java.md` and `deployment_java.md`
  RFC #1502 -- 2fdab722f^ `docs/typescript/mesh-functions.md`

They run against the REAL repository for the evidence half (the real route
inventory, the real starter `pom.xml`, the real handlers), because a fixture
repo would prove only that the checker can read a fixture.
"""

import pathlib
import sys

import pytest

# Imported by name rather than loaded from a spec: the checker's module-level
# `@dataclass`es need their own module registered in `sys.modules` to resolve
# annotations, which a bare `exec_module` does not do.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_doc_claims as cdc  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def served():
    return cdc.collect_served_paths(ROOT)


def _doc(tmp_path: pathlib.Path, name: str, body: str) -> pathlib.Path:
    path = tmp_path / name
    path.write_text(body)
    return path


# ---------------------------------------------------------------------------
# The corpus as it stands must be clean, or nothing below means anything.
# ---------------------------------------------------------------------------


def test_repository_is_clean():
    assert cdc.run(ROOT) == 0


# ---------------------------------------------------------------------------
# #1499: three surfaces claimed the Spring Boot starter integrates with
# Actuator. Two carried the claim in prose; one was a curl that 404s.
# ---------------------------------------------------------------------------

HEALTH_JAVA_1499 = """\
## Spring Boot Health Actuator

The MCP Mesh Spring Boot starter automatically integrates with Spring Boot's \
health actuator. The `/actuator/health` endpoint includes mesh status:

```bash
curl http://localhost:8080/actuator/health
```
"""

DEPLOYMENT_JAVA_1499 = """\
### Health Checks

Spring Boot agents automatically expose `/actuator/health`. The MCP Mesh \
starter integrates with Spring Boot's health system.
"""


def test_1499_curl_that_404s_is_caught(tmp_path, served):
    doc = _doc(tmp_path, "health_java.md", HEALTH_JAVA_1499)
    findings = cdc.check_curl_paths([doc], ROOT, served)
    assert len(findings) == 1
    assert "/actuator/health" in findings[0].detail


def test_1499_prose_claims_are_caught(tmp_path):
    docs = [
        _doc(tmp_path, "health_java.md", HEALTH_JAVA_1499),
        _doc(tmp_path, "deployment_java.md", DEPLOYMENT_JAVA_1499),
    ]
    findings = cdc.check_dependency_claims(docs, ROOT)
    assert {f.doc.rsplit("/", 1)[-1] for f in findings} == {
        "health_java.md",
        "deployment_java.md",
    }


def test_1499_corrected_prose_passes(tmp_path):
    """The fix documented the absence rather than deleting the subject.

    A checker that could not tell a denial from an assertion would have made
    that fix impossible, and the page would have gone silent on the one
    question every Spring developer asks.
    """
    corrected = _doc(
        tmp_path,
        "health_java.md",
        "Actuator is not a starter dependency, and mesh registers no "
        "`HealthIndicator` - deliberately. Actuator aggregates every "
        "registered indicator (datasource, disk, mail), while mesh gates "
        "traffic only on what `@MeshHealthCheck` says gates it.\n",
    )
    assert cdc.check_dependency_claims([corrected], ROOT) == []


def test_dependency_claim_evidence_is_read_from_the_build_file():
    """The Actuator entry must be answering from the POM, not from a constant."""
    claim = next(c for c in cdc.DEPENDENCY_CLAIMS if c.term == "actuator")
    pom = ROOT / claim.build_file
    assert pom.exists(), "the starter POM moved; the claim has no evidence"
    assert claim.evidence.lower() not in pom.read_text().lower(), (
        "the starter now declares Actuator. That is a product change: the "
        "pages that say it does not have to change with it, and this check "
        "stops applying."
    )


# ---------------------------------------------------------------------------
# RFC #1502: `/ready` reports the mesh runtime and is unmoved by the health
# verdict, so a withdrawn gateway keeps its Service endpoints.
# ---------------------------------------------------------------------------

MESH_FUNCTIONS_1502 = """\
`healthCheck` is what lets a provider take itself out of rotation. While it \
returns `{ status: "unhealthy" }` (or `false`) the agent stops heartbeating, \
the registry withdraws it, and consumers resolve to another provider. The \
verdict also drives the probe endpoints: `/ready` and `/health` answer 200 \
only while it reports `healthy`. `MCP_MESH_HEALTH_CHECK_TTL` overrides \
`healthCheckTtl`.
"""

MESH_FUNCTIONS_CORRECTED = """\
`healthCheck` is what lets a provider take itself out of rotation. The \
verdict drives `/health`, which answers 200 only while it reports `healthy`. \
It does not drive `/ready`, which reports whether the mesh runtime is up: \
pausing the heartbeat is the whole withdrawal, and a 503 on `/ready` would \
additionally drop the pod from the Service that mesh traffic arrives on.
"""


def test_1502_ready_coupling_is_caught(tmp_path):
    doc = _doc(tmp_path, "mesh-functions.md", MESH_FUNCTIONS_1502)
    findings = cdc.check_verdict_coupling(ROOT, [doc])
    assert len(findings) == 1
    assert "/ready" in findings[0].detail


def test_1502_corrected_prose_passes(tmp_path):
    doc = _doc(tmp_path, "mesh-functions.md", MESH_FUNCTIONS_CORRECTED)
    assert cdc.check_verdict_coupling(ROOT, [doc]) == []


def test_1502_pre_rfc_deployment_bullet_is_caught(tmp_path):
    """The bullet `deployment_java.md` carried before RFC #1502 step 2.

    It is the other real shape of this mistake: not a sentence, a list item,
    and it says "reflects your" rather than "answers 200 only while".
    """
    doc = _doc(
        tmp_path,
        "deployment_java.md",
        "- `/ready` - `readinessProbe`. Whether traffic should be routed "
        "here; reflects your `@MeshHealthCheck` on top of the mesh runtime "
        "state.\n",
    )
    findings = cdc.check_verdict_coupling(ROOT, [doc])
    assert len(findings) == 1


def test_1502_inverted_denial_is_caught(tmp_path):
    """"Your `health_check` does not reach it" is what every deployment page
    says today, so dropping the "does not" is the shape the next regression
    takes. The affirmative must go red."""
    doc = _doc(
        tmp_path,
        "deployment.md",
        "- `/ready` - `readinessProbe`. Whether the mesh runtime is up. Your "
        "`health_check` reaches it.\n",
    )
    assert len(cdc.check_verdict_coupling(ROOT, [doc])) == 1


def test_1502_current_denial_passes(tmp_path):
    doc = _doc(
        tmp_path,
        "deployment.md",
        "- `/ready` - `readinessProbe`. Whether the mesh runtime is up. Your "
        "`health_check` does not reach it.\n",
    )
    assert cdc.check_verdict_coupling(ROOT, [doc]) == []


def test_contrasting_clause_is_not_guessed_at(tmp_path):
    """Two endpoints being compared is the judgement this cannot make.

    `health.md` genuinely says this, and reporting it would be a false alarm
    that gets 'fixed' by rewording correct prose -- the worst outcome for a
    check over hand-written docs.
    """
    doc = _doc(
        tmp_path,
        "health.md",
        "Those verdicts show on the diagnostic surface only: `/health` "
        "answers 503 while `/ready` is unmoved.\n",
    )
    assert cdc.check_verdict_coupling(ROOT, [doc]) == []


# ---------------------------------------------------------------------------
# The code half of check C. These are live assertions about today's runtimes,
# not regression fixtures: nothing else pins RFC #1502's contract in source.
# ---------------------------------------------------------------------------


def test_handler_facts_cover_every_runtime():
    runtimes = {f.runtime for f in cdc.HANDLER_FACTS}
    assert runtimes == {"python", "typescript", "java"}
    ready = {f.runtime for f in cdc.HANDLER_FACTS if f.path == "/ready"}
    assert ready == {"python", "typescript", "java"}, (
        "a runtime whose /ready is unpinned can grow a verdict dependency "
        "without any check noticing"
    )


def test_no_ready_handler_consults_the_verdict():
    assert cdc.check_handler_facts(ROOT) == []


@pytest.mark.parametrize(
    "fact", cdc.HANDLER_FACTS, ids=lambda f: f"{f.runtime}{f.path}:{f.site[-24:]}"
)
def test_handler_bodies_are_located_and_bounded(fact):
    """A body the extractor cannot find, or one that swallowed the file, would
    make `check_handler_facts` assert nothing while reporting ok."""
    text = (ROOT / fact.site).read_text()
    body = cdc._handler_body(text, fact.handler)
    assert body is not None
    lines = body.splitlines()
    assert 1 < len(lines) < len(text.splitlines()) // 2


# ---------------------------------------------------------------------------
# The guards on the maintained halves.
# ---------------------------------------------------------------------------


def test_inventory_anchors_hold():
    assert cdc.check_inventory_anchors(cdc.collect_served_paths(ROOT)) == []


def test_an_empty_inventory_fails_rather_than_passing_everything():
    """The failure mode that would make check A worthless.

    If a runtime changes registration idiom, the extractor returns fewer paths
    and every curl example passes for the wrong reason. The anchors are the
    only thing standing between that and a green run.
    """
    empty = {runtime: set() for runtime in cdc.INVENTORY_ANCHORS}
    assert cdc.check_inventory_anchors(empty)


def test_supplement_sites_still_prove_their_paths():
    assert cdc.check_supplement_sites(ROOT) == []


def test_supplement_with_stale_evidence_fails(tmp_path):
    stale = cdc.Supplement(
        path="/nowhere",
        runtime="python",
        why="fixture",
        site="scripts/check_doc_claims.py",
        evidence="this string is not in the checker",
    )
    original = cdc.SUPPLEMENTS
    cdc.SUPPLEMENTS = (stale,)
    try:
        assert cdc.check_supplement_sites(ROOT)
    finally:
        cdc.SUPPLEMENTS = original


def test_illustrative_exemptions_are_all_still_used():
    assert cdc.check_illustrative_still_used(cdc.iter_docs(ROOT), ROOT) == []


def test_unused_illustrative_exemption_fails(tmp_path):
    original = cdc.ILLUSTRATIVE_PATHS
    cdc.ILLUSTRATIVE_PATHS = (
        cdc.IllustrativePath(path="/no-doc-curls-this", why="fixture"),
    )
    try:
        assert cdc.check_illustrative_still_used(cdc.iter_docs(ROOT), ROOT)
    finally:
        cdc.ILLUSTRATIVE_PATHS = original


# ---------------------------------------------------------------------------
# Pieces.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern,path,want",
    [
        ("/agents/:agent_id", "/agents/hello-world", True),
        ("/agents/:agent_id", "/agents/a/b", False),
        ("/agents", "/agents/", True),
        ("/jobs/*path", "/jobs/a/b/c", True),
        ("/payments/student/{studentId}", "/payments/student/42", True),
        ("/health", "/actuator/health", False),
        ("/health", "/healthz", False),
    ],
)
def test_path_matcher(pattern, path, want):
    assert bool(cdc.path_matcher(pattern).match(path)) is want


@pytest.mark.parametrize(
    "url,host,path",
    [
        ("http://localhost:8080/actuator/health", "localhost:8080", "/actuator/health"),
        ("http://localhost:8080/api/greet?name=World", "localhost:8080", "/api/greet"),
        ("https://raw.githubusercontent.com/x/y.sh", "raw.githubusercontent.com", "/x/y.sh"),
    ],
)
def test_split_url(url, host, path):
    assert cdc.split_url(url) == (host, path)


def test_external_hosts_are_not_checked(tmp_path, served):
    """Somebody else's server is not this repo's claim to make."""
    doc = _doc(
        tmp_path,
        "a2a.md",
        "```bash\ncurl https://upstream.example.com/agents/forecast\n```\n",
    )
    assert cdc.check_curl_paths([doc], ROOT, served) == []


def test_curl_folds_shell_continuations(tmp_path, served):
    doc = _doc(
        tmp_path,
        "testing.md",
        "```bash\ncurl -s -X POST \\\n  http://localhost:8080/not-a-real-path \\\n"
        '  -d \'{}\'\n```\n',
    )
    findings = cdc.check_curl_paths([doc], ROOT, served)
    assert len(findings) == 1
    assert "/not-a-real-path" in findings[0].detail


def test_fenced_code_is_not_prose(tmp_path):
    """A sample that mentions a term is not a claim about the build file."""
    doc = _doc(
        tmp_path,
        "x.md",
        "```xml\n<artifactId>spring-boot-starter-actuator</artifactId>\n```\n",
    )
    assert cdc.check_dependency_claims([doc], ROOT) == []


@pytest.mark.parametrize(
    "clause,want",
    [
        ("`/ready` and `/health` answer 200", ["/ready", "/health"]),
        ("`/health` answers 503 while `/ready` is unmoved", []),
        ("`/ready` reports the runtime, and a 503 on `/ready` drops it", ["/ready"]),
        ("nothing here", []),
    ],
)
def test_clause_subjects(clause, want):
    assert cdc.clause_subjects(clause) == want


def test_markdown_blocks_keep_a_paragraph_whole():
    blocks = cdc.markdown_blocks("one. two.\nthree.\n\nfour.\n")
    assert [b for _, b in blocks] == ["one. two. three.", "four."]


def test_markdown_clauses_split_a_paragraph():
    clauses = [c for _, c in cdc.markdown_clauses("one. two.\nthree.\n")]
    assert clauses == ["one.", "two.", "three."]
