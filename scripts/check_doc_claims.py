#!/usr/bin/env python3
"""Connect prose claims in the shipped docs to the code they describe.

`src/core/cli/man/content/<topic>.md`, `<topic>_java.md` and
`<topic>_typescript.md` are hand-maintained parallel surfaces, and `docs/`
restates the same facts a third time. A claim written once and copied into a
sibling has nothing checking it, and the man corpus tests in
`src/core/cli/man/renderer_test.go` cannot help: they assert that markup
*renders*, not that sentences are *true*.

Issue #1500 filed this after the failure bit twice:

  #1499 -- three surfaces said the Spring Boot starter integrates with
  Actuator. `mcp-mesh-spring-boot-starter/pom.xml` has no Actuator dependency
  and `MeshHealthCheckBeanPostProcessor` records that registering a
  `HealthIndicator` was considered and rejected. One of the three was
  `curl http://localhost:8080/actuator/health`, which 404s on a stock agent --
  a false claim a developer RUNS and then reasonably concludes their agent is
  broken.

  RFC #1502 -- `docs/typescript/mesh-functions.md` said `/ready` and `/health`
  answer 200 only while the agent reports healthy. `/ready` reports the mesh
  runtime and is unmoved by the verdict; that is the whole point of the RFC, so
  that a withdrawn gateway keeps its Service endpoints. A reader following that
  page would expect their pod to leave Service endpoints on a vendor outage.

Three checks, in the order of value #1500 puts them in.

CURL PATHS (check A). Every `curl` example naming a local host must name a path
something in this repo actually serves. The served set is derived from source
-- Go route registrations, FastAPI/Starlette decorators, Hono/Express
registrations, Spring mappings -- across the runtimes AND `examples/`, because
a doc that curls `/plan` is teaching the tutorial gateway, which defines it.
This is the check that catches the Actuator `curl` on its own.

DEPENDENCY CLAIMS (check B). A general "no page claims a dependency the module
does not declare" is not tractable; an explicit table of
(claim term -> build file -> evidence) is. If the build file does not carry the
evidence, the term may still appear -- documented absence is often the right
answer, and #1499 chose it -- but only in a NEGATED mention. This catches the
two prose surfaces of #1499 that carried no `curl`.

VERDICT COUPLING (check C). #1500 calls this the valuable and hardest one, and
it is only tractable in halves, so it is built in halves and both are asserted:

  1. The code half is exact. For each runtime, the named `/ready` handler must
     not reference the health-verdict symbols, and the named `/health` handler
     must. That is RFC #1502's contract stated where it can be mechanically
     checked, and nothing else pins it.
  2. The doc half is a bounded scan, NOT prose comprehension. It looks for the
     specific coupling idioms these pages use ("reflects your", "drives",
     "answers 200 only while", ...) inside one markdown unit that also names a
     probe path, and requires the polarity to match part 1. It is deliberately
     narrow: see WHAT THIS CANNOT SEE.

WHAT THIS CANNOT SEE
  - Whether a sentence with no coupling idiom is true. Check C recognises the
    idioms this corpus uses to express "endpoint X is driven by the health
    check". A page that states the same falsehood in words not on that list
    passes. The list is a floor, not a parser, and it must not be treated as
    licence to stop reading the prose in review -- see
    `.claude/review-checklist.md`.
  - Any claim that is not a path, a dependency name, or a verdict coupling.
    Most of what these pages assert is still checked by a human alone.
  - Whether a served path is served on the port or by the runtime the example
    implies. The inventory is path-level and repo-wide.

Usage: python3 scripts/check_doc_claims.py   (run from anywhere)
       python3 scripts/check_doc_claims.py --list-paths
Exit code 0 = every checked claim is connected to code that backs it.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Documents whose claims are checked.
# ---------------------------------------------------------------------------

# Globs, relative to the repo root. Deliberately every man page including the
# `_java` / `_typescript` variants, which no existing test samples at all.
DOC_GLOBS = (
    "src/core/cli/man/content/*.md",
    "docs/**/*.md",
    "helm/*/README.md",
    "README.md",
)

# Directories whose markdown is not a claim about this repo's behaviour.
DOC_SKIP_PARTS = ("node_modules", "site", "target", "dist", ".venv")


def iter_docs(root: Path) -> list[Path]:
    seen: dict[Path, None] = {}
    for pattern in DOC_GLOBS:
        for path in sorted(root.glob(pattern)):
            if any(part in DOC_SKIP_PARTS for part in path.parts):
                continue
            seen.setdefault(path, None)
    return list(seen)


# ---------------------------------------------------------------------------
# Route inventory: what the code actually serves.
# ---------------------------------------------------------------------------

SOURCE_SKIP_PARTS = (
    "node_modules",
    "dist",
    "build",
    "target",
    ".venv",
    "__pycache__",
    "generated_client",
)


def _is_source_of_interest(path: Path) -> bool:
    if any(part in SOURCE_SKIP_PARTS for part in path.parts):
        return False
    name = path.name
    # Test sources register throwaway routes; they are not a contract.
    if name.endswith("_test.go") or name.endswith(".test.ts"):
        return False
    if name.startswith("test_") or name.endswith("_test.py"):
        return False
    parts = path.parts
    if "tests" in parts or ("src" in parts and "test" in parts):
        return False
    return True


# Go: gin/httprouter registrations, plus the `Group("/api")` prefix idiom used
# by the meshui server. `options.BaseURL +` is the oapi-codegen generated form.
GO_ROUTE_RE = re.compile(
    r"\.(?:GET|POST|PUT|DELETE|HEAD|PATCH|OPTIONS|Handle|HandleFunc)\("
    r'\s*(?:[A-Za-z_.]+\s*\+\s*)?"(/[^"]*)"'
)
GO_GROUP_RE = re.compile(r'\.Group\(\s*"(/[^"]*)"')

# Python: FastAPI/Starlette decorators and imperative registration, plus the
# `X_PATH = "/livez"` module constants the probe endpoints are registered from
# and the `mount_path = "/mcp"` the MCP app is mounted at.
PY_ROUTE_RE = re.compile(
    r"(?:@[A-Za-z_][\w.]*|\b[A-Za-z_][\w.]*)"
    r"\.(?:get|post|put|delete|head|patch|api_route|add_api_route|mount|route|"
    r"add_route|add_websocket_route)\("
    r"\s*[\"'](/[^\"']*)[\"']"
)
PY_PATH_CONST_RE = re.compile(
    r"^\s*[A-Z_]*(?:PATH|ROUTE|ENDPOINT|MOUNT)\s*=\s*[\"'](/[^\"']*)[\"']", re.M
)

# TypeScript: Express routers and FastMCP's Hono app (`app.on([...], "/x", h)`).
TS_ROUTE_RE = re.compile(
    r"\.(?:get|post|put|delete|head|patch|all|use|on)\("
    r"\s*(?:\[[^\]]*\]\s*,\s*)?[\"'`](/[^\"'`]*)[\"'`]"
)

# Java: Spring mappings, with the class-level `@RequestMapping("/api")` prefix
# composed against the method-level mappings in the same file.
JAVA_MAPPING_RE = re.compile(
    r"@(?:Get|Post|Put|Delete|Patch|Request)Mapping\("
    r'\s*(?:value\s*=\s*)?"(/[^"]*)"'
)
JAVA_CLASS_PREFIX_RE = re.compile(
    r'@RequestMapping\(\s*(?:value\s*=\s*)?"(/[^"]*)"[^)]*\)\s*(?:@\w+(?:\([^)]*\))?\s*)*'
    r"(?:public\s+|final\s+|abstract\s+)*class\b"
)


def _strip_comment_lines(text: str, markers: tuple[str, ...]) -> str:
    """Drop whole-line comments so JSDoc examples do not enter the inventory.

    `api-runtime.ts` documents `app.post("/compute", mesh.route(...))` in a
    docblock. Counting that as a served path would let a doc curl `/compute`
    on any agent and stay green.
    """
    kept = []
    for line in text.split("\n"):
        if line.lstrip().startswith(markers):
            continue
        kept.append(line)
    return "\n".join(kept)


def collect_served_paths(root: Path) -> dict[str, set[str]]:
    """Return {runtime: {path pattern}} for everything this repo serves.

    Runtimes are the four the mesh ships plus `examples`, whose routes are
    real: a tutorial page that curls `/plan` is describing a gateway whose
    source is in this repo, and treating that as unserved would be wrong.
    """
    found: dict[str, set[str]] = {
        "go": set(),
        "python": set(),
        "typescript": set(),
        "java": set(),
        "examples": set(),
    }

    def bucket(path: Path, default: str) -> str:
        return "examples" if "examples" in path.parts else default

    for path in sorted((root / "src" / "core").rglob("*.go")):
        if not _is_source_of_interest(path):
            continue
        text = _strip_comment_lines(path.read_text(encoding="utf-8"), ("//",))
        literals = set(GO_ROUTE_RE.findall(text))
        prefixes = set(GO_GROUP_RE.findall(text))
        found["go"] |= literals
        found["go"] |= {_join(p, lit) for p in prefixes for lit in literals}

    py_roots = [root / "src" / "runtime" / "python", root / "examples"]
    for py_root in py_roots:
        for path in sorted(py_root.rglob("*.py")):
            if not _is_source_of_interest(path):
                continue
            text = _strip_comment_lines(path.read_text(encoding="utf-8"), ("#",))
            hits = set(PY_ROUTE_RE.findall(text)) | set(PY_PATH_CONST_RE.findall(text))
            found[bucket(path, "python")] |= hits

    ts_roots = [root / "src" / "runtime" / "typescript" / "src", root / "examples"]
    for ts_root in ts_roots:
        for path in sorted(ts_root.rglob("*.ts")):
            if not _is_source_of_interest(path):
                continue
            text = _strip_comment_lines(
                path.read_text(encoding="utf-8"), ("//", "*", "/*")
            )
            found[bucket(path, "typescript")] |= set(TS_ROUTE_RE.findall(text))

    java_roots = [root / "src" / "runtime" / "java", root / "examples"]
    for java_root in java_roots:
        for path in sorted(java_root.rglob("*.java")):
            if not _is_source_of_interest(path):
                continue
            raw = path.read_text(encoding="utf-8")
            prefixes = set(JAVA_CLASS_PREFIX_RE.findall(raw))
            text = _strip_comment_lines(raw, ("//", "*", "/*"))
            literals = set(JAVA_MAPPING_RE.findall(text))
            key = bucket(path, "java")
            found[key] |= literals
            found[key] |= {_join(p, lit) for p in prefixes for lit in literals}

    return found


def _join(prefix: str, suffix: str) -> str:
    return (prefix.rstrip("/") + "/" + suffix.lstrip("/")).replace("//", "/")


# A path served by a registration this extractor cannot read as a literal.
# Each entry cites the site it was read from, and `check_supplement_sites`
# re-reads that site every run: if the evidence moves or is renamed, the
# supplement fails rather than quietly outliving the route it stands for.
# This is what stops the maintained half from becoming the stale list it is
# meant to replace.
@dataclass(frozen=True)
class Supplement:
    path: str
    runtime: str
    why: str
    site: str  # repo-relative file
    evidence: str  # substring that must still be present at `site`


SUPPLEMENTS: tuple[Supplement, ...] = (
    Supplement(
        path="/mcp",
        runtime="python",
        why="FastMCP is mounted at a path held in a local variable, so the "
        "literal is on the assignment rather than on the mount call.",
        site="src/runtime/python/_mcp_mesh/pipeline/mcp_startup/fastapiserver_setup.py",
        evidence='mount_path = "/mcp"',
    ),
    Supplement(
        path="/mcp",
        runtime="typescript",
        why="FastMCP owns the MCP endpoint, so no SDK source registers it. "
        "The proxy proves the agreed path by normalising every peer endpoint "
        "onto it.",
        site="src/runtime/typescript/src/proxy.ts",
        evidence='endsWith("/mcp")',
    ),
    Supplement(
        path="/mcp",
        runtime="java",
        why="The MCP endpoint is configured on the Spring transport provider "
        "from a constant, not declared with a @RequestMapping.",
        site="src/runtime/java/mcp-mesh-spring-boot-starter/src/main/java/io/mcpmesh/spring/MeshMcpServerConfiguration.java",
        evidence='MCP_ENDPOINT = "/mcp"',
    ),
)


# Paths a doc curls that nothing serves BY DESIGN: they stand in for an
# endpoint the reader writes. Each must stay referenced by some doc -- an
# entry no doc uses is a stale exemption and fails, so this list cannot grow
# quietly the way the prose it guards did.
@dataclass(frozen=True)
class IllustrativePath:
    path: str
    why: str


ILLUSTRATIVE_PATHS: tuple[IllustrativePath, ...] = (
    IllustrativePath(
        path="/api/process",
        why="headers*.md: stands in for the reader's own gateway route, in an "
        "example about what mesh forwards, not about what mesh serves.",
    ),
)


# If the extractor stops matching a runtime's idiom it returns fewer paths and
# every curl example passes for the wrong reason. These anchors are re-derived
# every run: they are the guard on the mechanical half.
INVENTORY_ANCHORS: dict[str, tuple[str, ...]] = {
    "go": ("/health", "/agents", "/heartbeat", "/jobs"),
    "python": ("/livez", "/ready", "/health", "/startupz"),
    "typescript": ("/livez", "/ready", "/health", "/startupz"),
    "java": ("/livez", "/ready", "/health", "/startupz"),
    "examples": ("/plan",),
}


def path_matcher(pattern: str) -> re.Pattern[str]:
    """Compile a route pattern into a matcher for a concrete request path.

    Handles the four parameter spellings in play: gin's `:id` and `*path`,
    Spring's `{id}` and Starlette's `{id}`.
    """
    out = ["^"]
    for segment in pattern.strip("/").split("/"):
        if not segment:
            continue
        out.append("/")
        if segment.startswith("*"):
            out.append(".+")
        elif segment.startswith(":") or (
            segment.startswith("{") and segment.endswith("}")
        ):
            out.append("[^/]+")
        else:
            out.append(re.escape(segment))
    if len(out) == 1:
        out.append("/")
    out.append("/?$")
    return re.compile("".join(out))


# ---------------------------------------------------------------------------
# Check A: curl examples name a path something serves.
# ---------------------------------------------------------------------------

# Only hosts that mean "something you are running". An external host is
# somebody else's contract and this repo cannot assert anything about it.
LOCAL_HOST_RE = re.compile(
    r"^(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|host\.docker\.internal|"
    r"[\w.$%{}<>-]+:\d+|\$\{?[A-Z_]+\}?)$"
)
URL_RE = re.compile(r"https?://[^\s'\"`)\\|]+")


@dataclass
class Finding:
    doc: str
    line: int
    detail: str


def _rel(doc: Path, root: Path) -> str:
    """Repo-relative label, falling back to the absolute path.

    Tests hand these checks fixture documents outside the tree; a label is
    cosmetic and must not be the reason a check cannot be exercised.
    """
    try:
        return str(doc.relative_to(root))
    except ValueError:
        return str(doc)


def _curl_urls(text: str):
    """Yield (line number, url) for every URL that is an argument to curl.

    Shell line continuations are folded first: the URL is regularly on the
    line after the `curl`.
    """
    lines = text.split("\n")
    folded: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        start = i
        buf = lines[i]
        while buf.rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            buf = buf.rstrip().rstrip("\\") + " " + lines[i]
        folded.append((start + 1, buf))
        i += 1

    for lineno, buf in folded:
        idx = buf.find("curl")
        if idx == -1:
            continue
        for url in URL_RE.findall(buf[idx:]):
            yield lineno, url.rstrip(".,;:)\"'")


def split_url(url: str) -> tuple[str, str]:
    body = url.split("://", 1)[1]
    host, _, rest = body.partition("/")
    path = "/" + rest
    path = path.split("?", 1)[0].split("#", 1)[0]
    return host, path


def check_curl_paths(
    docs: list[Path], root: Path, served: dict[str, set[str]]
) -> list[Finding]:
    matchers = [
        path_matcher(p) for paths in served.values() for p in paths if p
    ]
    matchers += [path_matcher(s.path) for s in SUPPLEMENTS]
    illustrative = {i.path for i in ILLUSTRATIVE_PATHS}

    findings: list[Finding] = []
    for doc in docs:
        rel = _rel(doc, root)
        for lineno, url in _curl_urls(doc.read_text(encoding="utf-8")):
            host, path = split_url(url)
            if not LOCAL_HOST_RE.match(host):
                continue
            if path in illustrative:
                continue
            if any(m.match(path) for m in matchers):
                continue
            findings.append(
                Finding(
                    rel,
                    lineno,
                    f"curl example targets {path!r}, which nothing in this "
                    f"repo serves (url: {url}). Either the claim is wrong, or "
                    f"the route exists somewhere this checker cannot read it "
                    f"-- add a Supplement with the site that proves it.",
                )
            )
    return findings


def check_illustrative_still_used(
    docs: list[Path], root: Path
) -> list[Finding]:
    used = set()
    for doc in docs:
        for _, url in _curl_urls(doc.read_text(encoding="utf-8")):
            used.add(split_url(url)[1])
    findings = []
    for entry in ILLUSTRATIVE_PATHS:
        if entry.path not in used:
            findings.append(
                Finding(
                    "scripts/check_doc_claims.py",
                    0,
                    f"ILLUSTRATIVE_PATHS still exempts {entry.path!r}, which "
                    f"no doc curls any more. Delete the entry.",
                )
            )
    return findings


def check_supplement_sites(root: Path) -> list[Finding]:
    findings = []
    for sup in SUPPLEMENTS:
        site = root / sup.site
        if not site.exists():
            findings.append(
                Finding(
                    "scripts/check_doc_claims.py",
                    0,
                    f"SUPPLEMENTS cites {sup.site}, which no longer exists. "
                    f"The claim that {sup.path!r} is served needs a new site.",
                )
            )
            continue
        if sup.evidence not in site.read_text(encoding="utf-8"):
            findings.append(
                Finding(
                    sup.site,
                    0,
                    f"SUPPLEMENTS claims {sup.path!r} is served here, on the "
                    f"evidence of {sup.evidence!r}, which is no longer in the "
                    f"file. Re-read the registration and update or drop the "
                    f"entry.",
                )
            )
    return findings


def check_inventory_anchors(served: dict[str, set[str]]) -> list[Finding]:
    findings = []
    for runtime, anchors in INVENTORY_ANCHORS.items():
        have = served.get(runtime, set())
        for anchor in anchors:
            if anchor not in have:
                findings.append(
                    Finding(
                        "scripts/check_doc_claims.py",
                        0,
                        f"route extraction found no {anchor!r} for {runtime}. "
                        f"Either the route was removed, or the registration "
                        f"idiom changed and this extractor is now reading "
                        f"less than it thinks. Do not relax the anchor to go "
                        f"green -- an empty inventory passes every curl.",
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Check B: no page claims a dependency the module does not declare.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DependencyClaim:
    term: str  # case-insensitive word the docs use for the dependency
    build_file: str  # repo-relative build file that would declare it
    evidence: str  # case-insensitive substring that proves the declaration
    subject: str  # what the module is, for the failure message


DEPENDENCY_CLAIMS: tuple[DependencyClaim, ...] = (
    DependencyClaim(
        term="actuator",
        build_file="src/runtime/java/mcp-mesh-spring-boot-starter/pom.xml",
        evidence="actuator",
        subject="the MCP Mesh Spring Boot starter",
    ),
)

# A mention of an undeclared dependency is fine when the page is saying it is
# absent -- #1499 was fixed by documenting the absence, not by deleting the
# subject. These are the markers that make a mention a denial. They are matched
# in the same markdown unit as the term.
NEGATION_MARKERS = (
    r"\bnot\b",
    r"\bno\b",
    r"\bnever\b",
    r"\bnothing\b",
    r"\bwithout\b",
    r"\bneither\b",
    r"\bdoes ?n[o']t\b",
    r"\bis ?n[o']t\b",
    r"\brather than\b",
    r"\binstead of\b",
    r"\bif your application adds\b",
)
NEGATION_RE = re.compile("|".join(NEGATION_MARKERS), re.I)


def markdown_blocks(text: str) -> list[tuple[int, str]]:
    """Split markdown into (line number, block) chunks that carry one claim.

    A block is one paragraph, one list item with its wrapped continuation
    lines, or one table row. Fenced blocks and headings are dropped: a code
    sample is not a prose claim, and a heading is too short to carry a
    polarity.

    Block granularity is what check B wants. A paragraph that opens by denying
    a dependency and then explains what the absent thing does is one claim,
    and splitting it into sentences would report the explanation as an
    unqualified assertion.
    """
    blocks: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_line = 0
    in_fence = False

    def flush():
        nonlocal buf
        if buf:
            joined = " ".join(s.strip() for s in buf).strip()
            if joined:
                blocks.append((buf_line, joined))
        buf = []

    for i, line in enumerate(text.split("\n"), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            flush()
            continue
        if in_fence:
            continue
        if not stripped or stripped.startswith("#"):
            flush()
            continue
        if stripped.startswith("|"):
            flush()
            for cell in stripped.strip("|").split("|"):
                cell = cell.strip()
                if cell:
                    blocks.append((i, cell))
            continue
        if re.match(r"^\s*(?:[-*+]\s|\d+\.\s)", line):
            flush()
        if not buf:
            buf_line = i
        buf.append(line)
    flush()
    return blocks


def markdown_clauses(text: str) -> list[tuple[int, str]]:
    """Blocks, split again on sentence terminators and the man pages' " - ".

    Clause granularity is what check C wants. A block regularly contrasts two
    endpoints ("`/health` answers 503 while `/ready` is unmoved"), and a check
    that asks which endpoint an idiom belongs to can only answer inside one
    clause.
    """
    clauses: list[tuple[int, str]] = []
    for lineno, block in markdown_blocks(text):
        for piece in re.split(r"(?<=[.!?])\s+|\s+-\s+|;\s+", block):
            piece = piece.strip()
            if piece:
                clauses.append((lineno, piece))
    return clauses


def check_dependency_claims(
    docs: list[Path], root: Path
) -> list[Finding]:
    findings: list[Finding] = []
    for claim in DEPENDENCY_CLAIMS:
        build_file = root / claim.build_file
        if not build_file.exists():
            findings.append(
                Finding(
                    "scripts/check_doc_claims.py",
                    0,
                    f"DEPENDENCY_CLAIMS points at {claim.build_file}, which "
                    f"does not exist. The claim has no evidence either way.",
                )
            )
            continue
        declared = (
            claim.evidence.lower() in build_file.read_text(encoding="utf-8").lower()
        )
        if declared:
            continue

        term_re = re.compile(re.escape(claim.term), re.I)
        for doc in docs:
            rel = _rel(doc, root)
            for lineno, unit in markdown_blocks(doc.read_text(encoding="utf-8")):
                if not term_re.search(unit):
                    continue
                if NEGATION_RE.search(unit):
                    continue
                findings.append(
                    Finding(
                        rel,
                        lineno,
                        f"asserts {claim.term!r} without qualification, but "
                        f"{claim.build_file} declares no {claim.evidence!r}, "
                        f"so {claim.subject} does not have it. Either the "
                        f"dependency belongs in the build file, or the page "
                        f"must say it is absent.\n      unit: {unit[:200]}",
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Check C: probe endpoints are documented with the polarity their handler has.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HandlerFact:
    runtime: str
    path: str
    site: str
    handler: str  # regex locating the handler body's opening
    consults_verdict: bool
    verdict_symbols: tuple[str, ...]  # symbols that read the health check
    note: str


# The code half of check C. `consults_verdict` is asserted against the handler
# body, so this table cannot drift away from the runtimes: if someone wires the
# verdict back into `/ready`, the assertion fails here before any doc is read.
HANDLER_FACTS: tuple[HandlerFact, ...] = (
    HandlerFact(
        runtime="python",
        path="/ready",
        site="src/runtime/python/_mcp_mesh/shared/health_check_manager.py",
        handler=r"def build_ready_response\(",
        consults_verdict=False,
        verdict_symbols=("get_health_check_result", "_last_health_check_result"),
        note="RFC #1502: a provider's readiness reports the mesh runtime "
        "only, so a withdrawn agent keeps its Service endpoints.",
    ),
    HandlerFact(
        runtime="python",
        path="/health",
        site="src/runtime/python/_mcp_mesh/shared/health_check_manager.py",
        handler=r"def build_health_response\(",
        consults_verdict=True,
        verdict_symbols=("get_health_check_result", "_last_health_check_result"),
        note="The diagnostic surface: nothing probes it, so it is free to "
        "carry the verdict.",
    ),
    HandlerFact(
        runtime="python",
        path="/ready",
        site="src/runtime/python/_mcp_mesh/pipeline/shared/health_endpoints.py",
        handler=r"async def ready\(",
        consults_verdict=False,
        verdict_symbols=("get_health_check_result",),
        note="The gateway pipeline's readiness, same rule as a provider's.",
    ),
    HandlerFact(
        runtime="python",
        path="/health",
        site="src/runtime/python/_mcp_mesh/pipeline/shared/health_endpoints.py",
        handler=r"async def health\(",
        consults_verdict=True,
        verdict_symbols=("get_health_check_result",),
        note="A withdrawn gateway must be observable somewhere.",
    ),
    HandlerFact(
        runtime="typescript",
        path="/ready",
        site="src/runtime/typescript/src/health-routes.ts",
        handler=r'app\.on\(\["GET", "HEAD"\], "/ready"',
        consults_verdict=False,
        verdict_symbols=("snapshot()", "getVerdict", "buildHealthBody"),
        note="RFC #1502, mirrored from Python.",
    ),
    HandlerFact(
        runtime="typescript",
        path="/health",
        site="src/runtime/typescript/src/health-routes.ts",
        handler=r'app\.on\(\["GET", "HEAD"\], "/health"',
        consults_verdict=True,
        verdict_symbols=("snapshot()", "getVerdict", "buildHealthBody"),
        note="The diagnostic surface.",
    ),
    HandlerFact(
        runtime="java",
        path="/ready",
        site="src/runtime/java/mcp-mesh-spring-boot-starter/src/main/java/io/mcpmesh/spring/MeshHealthController.java",
        handler=r"ResponseEntity<Map<String, Object>> ready\(",
        consults_verdict=False,
        verdict_symbols=("latestResult(", "healthChecks"),
        note="#1488 plus RFC #1502: a gateway that 503s readiness leaves its "
        "Service endpoints and takes the application down.",
    ),
    HandlerFact(
        runtime="java",
        path="/health",
        site="src/runtime/java/mcp-mesh-spring-boot-starter/src/main/java/io/mcpmesh/spring/MeshHealthController.java",
        handler=r"ResponseEntity<Map<String, Object>> health\(",
        consults_verdict=True,
        verdict_symbols=("latestResult(",),
        note="The diagnostic surface.",
    ),
    HandlerFact(
        runtime="typescript",
        path="/livez",
        site="src/runtime/typescript/src/livez-route.ts",
        handler=r'app\.on\(\["GET", "HEAD"\], "/livez"',
        consults_verdict=False,
        verdict_symbols=("getVerdict", "snapshot", "HealthVerdict"),
        note="Liveness consults nothing: a restart cannot fix a dependency.",
    ),
)


def _handler_body(text: str, handler_re: str) -> str | None:
    """Return the source of the handler the anchor names, or None.

    Language-agnostic and deliberately simple: from the anchor's line, read
    until the first non-blank line indented no further than the anchor. That
    rule alone would stop on a multi-line signature -- Python's
    ``def build_ready_response(\\n    agent_name,\\n) -> ...:`` closes at
    column 0 -- so it is only applied once the delimiters opened on the anchor
    line have balanced, which is the end of the signature in Python and the
    end of the whole registration in TypeScript's ``app.on(..., (c) => {...})``.

    The result is a superset of the handler in the TypeScript case and exact
    elsewhere, which is the safe direction: it can only make a "does not
    consult the verdict" assertion harder to pass, never easier.
    """
    match = re.search(handler_re, text)
    if match is None:
        return None
    line_start = text.rfind("\n", 0, match.start()) + 1
    lines = text[line_start:].split("\n")
    indent = len(lines[0]) - len(lines[0].lstrip())

    out: list[str] = []
    depth = 0
    signature_closed = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if (
            i > 0
            and signature_closed
            and stripped
            and len(line) - len(line.lstrip()) <= indent
        ):
            break
        out.append(line)
        depth += sum(line.count(c) for c in "([{") - sum(line.count(c) for c in ")]}")
        if i >= 0 and depth <= 0:
            signature_closed = True
    return "\n".join(out)


def check_handler_facts(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for fact in HANDLER_FACTS:
        site = root / fact.site
        if not site.exists():
            findings.append(
                Finding(
                    "scripts/check_doc_claims.py",
                    0,
                    f"HANDLER_FACTS cites {fact.site}, which no longer "
                    f"exists. {fact.runtime} {fact.path} needs a new site.",
                )
            )
            continue
        text = site.read_text(encoding="utf-8")
        body = _handler_body(text, fact.handler)
        if body is None:
            findings.append(
                Finding(
                    fact.site,
                    0,
                    f"HANDLER_FACTS cannot find the {fact.runtime} "
                    f"{fact.path} handler ({fact.handler!r}). The endpoint "
                    f"may have moved; docs are being checked against a fact "
                    f"nothing verifies until this is fixed.",
                )
            )
            continue
        consults = any(sym in body for sym in fact.verdict_symbols)
        if consults != fact.consults_verdict:
            expected = "consult" if fact.consults_verdict else "not consult"
            findings.append(
                Finding(
                    fact.site,
                    0,
                    f"{fact.runtime} {fact.path} should {expected} the health "
                    f"verdict and now does the opposite. {fact.note}\n"
                    f"      If the behaviour change is intended, every page "
                    f"describing {fact.path} has to change with it.",
                )
            )
    return findings


PROBE_PATHS = ("/livez", "/startupz", "/ready", "/health")

# The idioms this corpus uses to say "endpoint X is driven by the health
# check". Not a parser -- a floor. See WHAT THIS CANNOT SEE.
COUPLING_IDIOMS = (
    r"reflects?\s+(?:your|the|its|a)",
    r"driv(?:es|en by)",
    r"answers?\s+(?:200|503)\s+(?:only\s+)?(?:while|when|until|unless)",
    r"answers?\s+(?:200|503)\s+(?:only\s+)?(?:if|iff)",
    r"carr(?:y|ies)\s+(?:the\s+)?(?:same\s+)?verdict",
    r"report(?:s)?\s+(?:your|the)\s+(?:health[_ ]?check|healthCheck|verdict)",
    r"gated?\s+(?:on|by)",
    r"consults?\s+(?:the\s+)?(?:health[_ ]?check|healthCheck|verdict)",
    r"on top of",
    # "Your `health_check` does not reach it" is how every current deployment
    # page words the denial, so the affirmative is the shape the next mistake
    # will take. Same for the pre-RFC-#1502 "their check feeds `/health` only".
    r"\breach(?:es)?\b",
    r"\bfeeds?\b",
)
COUPLING_RE = re.compile("|".join(COUPLING_IDIOMS), re.I)

VERDICT_TERMS = re.compile(
    r"health[_ ]?check|healthCheck|MeshHealthCheck|\bverdict\b|"
    r"\bunhealthy\b|\bit reports\b|\bthe check\b",
    re.I,
)

# Denials of the coupling. Matched anywhere in the unit, because a unit is
# already one clause by the time it gets here.
DECOUPLING_RE = re.compile(
    r"\bdoes ?n[o']t\b|\bdo ?n[o']t\b|\bnot\b|\bnever\b|\bnothing\b|"
    r"\bunmoved\b|\bignores?\b|\brather than\b|\binstead of\b|"
    r"\band nothing else\b|\bonly whether\b|\bexcept\b|\bregardless\b",
    re.I,
)

# Check C's doc half runs over the pages that state the probe contract. This
# is a narrow list on purpose: the idiom scan is only trustworthy where the
# prose is about endpoints, and a repo-wide sweep would trade its precision
# for reach it does not need. Each entry is a page this contract is taught on.
PROBE_DOC_GLOBS = (
    "src/core/cli/man/content/health*.md",
    "src/core/cli/man/content/deployment*.md",
    "docs/concepts/health-discovery.md",
    "docs/python/mesh-decorators.md",
    "docs/typescript/mesh-functions.md",
    "docs/java/mesh-annotations.md",
    "docs/tutorial/day-10-whats-next.md",
    "helm/mcp-mesh-agent/README.md",
)


def probe_docs(root: Path) -> list[Path]:
    out: dict[Path, None] = {}
    for pattern in PROBE_DOC_GLOBS:
        for path in sorted(root.glob(pattern)):
            out.setdefault(path, None)
    return list(out)


PROBE_PATH_RE = re.compile("|".join(re.escape(p) for p in PROBE_PATHS))
# Text that joins two path mentions without saying anything about either:
# "`/ready` and `/health` answer 200 only while ..." predicates the idiom of
# both. Anything longer is a contrast ("`/health` answers 503 while `/ready`
# is unmoved") and the idiom belongs to one of them, which is exactly the
# judgement this cannot make.
BARE_CONJUNCTION_RE = re.compile(r"^[\s,`]*(?:and|or|/|,)?[\s,`]*$")


def clause_subjects(clause: str) -> list[str]:
    """Return the probe paths a clause's predicate applies to.

    Empty when the clause names several paths that are not simply listed
    together, because attributing the predicate would be a guess.
    """
    hits = [(m.start(), m.end(), m.group(0)) for m in PROBE_PATH_RE.finditer(clause)]
    if not hits:
        return []
    distinct: list[tuple[int, int, str]] = []
    for hit in hits:
        if not any(d[2] == hit[2] for d in distinct):
            distinct.append(hit)
    if len(distinct) == 1:
        return [distinct[0][2]]
    # Several distinct paths: they must be a bare list, and the whole run of
    # mentions must be contiguous, or the predicate is not shared.
    ordered = sorted(hits, key=lambda h: h[0])
    for left, right in zip(ordered, ordered[1:]):
        if not BARE_CONJUNCTION_RE.match(clause[left[1]:right[0]]):
            return []
    return [d[2] for d in distinct]


def check_verdict_coupling(
    root: Path, docs: list[Path] | None = None
) -> list[Finding]:
    """Assert documented probe polarity matches HANDLER_FACTS.

    A clause that names a probe path, uses a coupling idiom and names the
    verdict is a claim about whether that endpoint is driven by the health
    check. Only paths every runtime's handler agrees are verdict-FREE are
    checked; `/health` legitimately carries the verdict, and asserting the
    positive direction would mostly exempt itself, since half of what the
    corpus writes about `/health` opens with "Nothing probes it".

    This is a regression guard and, on a corrected corpus, asserts nothing:
    the clauses it would fail are the ones that were deleted to fix #1499 and
    RFC #1502. `scripts/test_check_doc_claims.py` replays both, which is what
    keeps it honest -- a guard nobody has seen fail is a guard nobody knows
    works.
    """
    polarity: dict[str, set[bool]] = {}
    for fact in HANDLER_FACTS:
        polarity.setdefault(fact.path, set()).add(fact.consults_verdict)

    findings: list[Finding] = []
    for doc in probe_docs(root) if docs is None else docs:
        rel = _rel(doc, root)
        text = doc.read_text(encoding="utf-8")
        seen: set[tuple[int, str]] = set()
        for lineno, unit in _coupling_units(text):
            subjects = [
                p
                for p in clause_subjects(unit)
                if polarity.get(p) == {False}
            ]
            if not subjects:
                continue
            if not COUPLING_RE.search(unit) or not VERDICT_TERMS.search(unit):
                continue
            if DECOUPLING_RE.search(unit):
                continue
            named = ", ".join(subjects)
            if (lineno, named) in seen:
                continue
            seen.add((lineno, named))
            findings.append(
                Finding(
                    rel,
                    lineno,
                    f"couples {named} to the health check, which no runtime's "
                    f"handler for it consults (see HANDLER_FACTS). A reader "
                    f"following this expects the pod to leave its Service "
                    f"endpoints on a dependency outage.\n      unit: "
                    f"{unit[:200]}",
                )
            )
    return findings


def _coupling_units(text: str):
    """Clauses, plus whole blocks that are about exactly one probe endpoint.

    Clause granularity alone misses the shape the deployment pages use, where
    the endpoint is a bullet's subject and its behaviour is stated sentences
    later:

        - `/ready` - `readinessProbe`. Whether traffic should be routed here;
          reflects your `@MeshHealthCheck` on top of the mesh runtime state.

    That bullet is the pre-RFC-#1502 text and is exactly the claim this check
    exists for, so a block naming ONE probe path and no other is evaluated
    whole -- everything in it predicates that endpoint. Blocks naming two are
    left to the clause pass, which is where the contrast cases are handled.
    """
    yield from markdown_clauses(text)
    for lineno, block in markdown_blocks(text):
        if len({m.group(0) for m in PROBE_PATH_RE.finditer(block)}) == 1:
            yield lineno, block


# ---------------------------------------------------------------------------


CHECKS = (
    ("route inventory anchors", lambda r, d, s: check_inventory_anchors(s)),
    ("supplement sites", lambda r, d, s: check_supplement_sites(r)),
    ("curl paths", lambda r, d, s: check_curl_paths(d, r, s)),
    ("illustrative-path exemptions", lambda r, d, s: check_illustrative_still_used(d, r)),
    ("dependency claims", lambda r, d, s: check_dependency_claims(d, r)),
    ("probe handler facts", lambda r, d, s: check_handler_facts(r)),
    ("probe verdict coupling", lambda r, d, s: check_verdict_coupling(r)),
)


def run(root: Path) -> int:
    docs = iter_docs(root)
    served = collect_served_paths(root)

    failed = 0
    for name, fn in CHECKS:
        findings = fn(root, docs, served)
        if findings:
            failed += len(findings)
            print(f"FAIL  {name}")
            for f in findings:
                where = f"{f.doc}:{f.line}" if f.line else f.doc
                print(f"    {where}: {f.detail}")
        else:
            print(f"ok    {name}")

    if failed:
        print(f"\n{failed} doc claim(s) are not backed by the code they describe.")
        print(
            "Fix the claim, not the check: a page that has to be reworded to "
            "pass is a page that was wrong."
        )
        return 1
    print("\nAll checked doc claims are backed by the code they describe.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--list-paths",
        action="store_true",
        help="print the derived route inventory and exit",
    )
    args = parser.parse_args()

    if args.list_paths:
        served = collect_served_paths(args.root)
        for runtime in sorted(served):
            print(f"[{runtime}]")
            for path in sorted(served[runtime]):
                print(f"  {path}")
        for sup in SUPPLEMENTS:
            print(f"[{sup.runtime}] {sup.path}  (supplement: {sup.site})")
        return 0

    return run(args.root)


if __name__ == "__main__":
    sys.exit(main())
