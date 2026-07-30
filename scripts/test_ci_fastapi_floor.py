#!/usr/bin/env python3
"""The 'older FastAPI' CI job must exercise the version the manifests declare
as the floor (#1409).

`@mesh.route` is the one place mesh reads and rebuilds FastAPI's own route
state, so a FastAPI release can break it (#1387/#1389/#1396). CI covers both
ends of the supported range: the main run resolves whatever pip gives it
(latest), and a second run pins an older one.

The older pin sat at 0.136.1 while the manifests declared `fastapi>=0.135.0`
(#1402). The lowest version a user could legally install was therefore BELOW
the lowest version CI exercised — supported on paper, untested in CI, which is
the exact defect shape #1402 fixed. The band is only two versions wide, but it
is the band where the attributes the route rebuild keys off are half-present
(`is_json_stream` in 0.134.0, `is_sse_stream` in 0.135.0), so it is the band
most likely to behave differently.

Asserting the equality here is what makes it structural: raising the manifest
floor without moving the CI pin, or vice versa, goes red in `pytest scripts/`
rather than waiting for someone to remember.

Stdlib only (`tomllib` is 3.11+), matching the scripts-test job, which
installs nothing but pytest.
"""

import importlib.util
import pathlib
import re
import tomllib

PROJECT_ROOT = pathlib.Path(__file__).parent.parent

CI_WORKFLOW = PROJECT_ROOT / ".github/workflows/ci.yml"

# Every place the FastAPI floor is declared. The two package manifests are the
# contract users install against; any requirements file that repeats the claim
# must state the same number, because drifting below the real floor there
# ships an image whose route suite was never green.
FLOOR_MANIFESTS = (
    "packaging/pypi/pyproject.toml",
    "src/runtime/python/pyproject.toml",
)

_spec = importlib.util.spec_from_file_location(
    "test_requirements_hygiene",
    pathlib.Path(__file__).with_name("test_requirements_hygiene.py"),
)
_hygiene = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hygiene)


def floor_requirements() -> tuple[str, ...]:
    """Requirements files that state a fastapi LOWER BOUND, discovered.

    This used to be a hardcoded one-entry tuple naming
    `examples/docker-examples/agents/base/requirements.txt`. #1404 deleted
    that file as orphaned build metadata — nothing copied it, nothing
    installed it — and a hardcoded list naming a deleted file is a check that
    fails for the wrong reason. Discovering the set instead means the next
    example to declare a fastapi floor is covered the day it lands, not the
    day someone remembers this module exists.

    A bare `fastapi` with no `>=` (as in examples/python/mesh-api) states no
    floor and therefore cannot disagree with one, so it is not collected.
    """
    out = []
    for path in _hygiene.requirement_files():
        for line in path.read_text(errors="replace").splitlines():
            if re.match(r"^fastapi\s*>=\s*[0-9]", line.strip()):
                out.append(str(path.relative_to(PROJECT_ROOT)))
                break
    return tuple(sorted(out))


def _manifest_floor(rel: str) -> str:
    """The `>=` bound of the fastapi requirement in a pyproject.toml."""
    data = tomllib.loads((PROJECT_ROOT / rel).read_text())
    for spec in data["project"]["dependencies"]:
        if re.match(r"^fastapi\b", spec):
            m = re.search(r">=\s*([0-9][^,\s;\[\]]*)", spec)
            assert m, f"{rel}: fastapi pin {spec!r} declares no >= floor"
            return m.group(1)
    raise AssertionError(f"{rel}: no fastapi dependency found")


def _requirements_floor_text(text: str, rel: str = "<text>") -> str:
    for line in text.splitlines():
        m = re.match(r"^fastapi\s*>=\s*([0-9][^,\s;#]*)", line.strip())
        if m:
            return m.group(1)
    raise AssertionError(f"{rel}: no `fastapi>=` line found")


def _requirements_floor(rel: str) -> str:
    return _requirements_floor_text((PROJECT_ROOT / rel).read_text(), rel)


def _ci_pin() -> str:
    """The version the 'older FastAPI' job installs."""
    text = CI_WORKFLOW.read_text()
    pins = re.findall(r'pip install "fastapi==([^"]+)"', text)
    assert len(pins) == 1, (
        f"expected exactly one pinned `pip install \"fastapi==...\"` in "
        f"{CI_WORKFLOW.name}, found {pins}. If a second older-FastAPI job is "
        "added, teach this check about it — an unchecked pin is how the "
        "original drift went unnoticed."
    )
    return pins[0]


def test_ci_older_fastapi_pin_is_the_declared_floor():
    pin = _ci_pin()
    for rel in FLOOR_MANIFESTS:
        floor = _manifest_floor(rel)
        assert pin == floor, (
            f"CI pins fastapi=={pin} but {rel} declares a floor of {floor}. "
            "The lowest installable version must be the lowest tested one — "
            "either move the CI pin to the floor, or raise the floor."
        )


def test_every_declared_fastapi_floor_agrees():
    """Both manifests, plus every requirements file that names a floor, state
    the same one. A split between them is a supported-range claim that depends
    on which file you read."""
    floors = {rel: _manifest_floor(rel) for rel in FLOOR_MANIFESTS}
    floors.update({rel: _requirements_floor(rel) for rel in floor_requirements()})
    assert len(set(floors.values())) == 1, floors


def test_floor_discovery_finds_a_bounded_requirements_file(tmp_path):
    """The discovery above replaced a hardcoded list, so it has to be shown
    finding something — an empty result would make the test above pass by
    scanning nothing, which is how the hardcoded list would have failed
    silently if it had been quietly emptied instead of deleted."""
    (tmp_path / "bounded").mkdir()
    (tmp_path / "bounded" / "requirements.txt").write_text("fastapi>=0.135.0\n")
    (tmp_path / "bare").mkdir()
    (tmp_path / "bare" / "requirements.txt").write_text("fastapi\nuvicorn\n")

    matched = [
        p
        for p in _hygiene.requirement_files(tmp_path)
        if any(
            re.match(r"^fastapi\s*>=\s*[0-9]", ln.strip())
            for ln in p.read_text().splitlines()
        )
    ]
    assert [p.parent.name for p in matched] == ["bounded"], matched
    assert _requirements_floor_text("fastapi>=0.135.0\n") == "0.135.0"


def test_no_superseded_include_router_version_in_ci_comments():
    """#1403 corrected the `include_router` figure across 8 sites; ci.yml:289
    was a 9th it missed. Lazy `include_router` (`original_router`) appears at
    0.137.0 — empirically 0.136.3 flattens, 0.137.0 is lazy — so a comment
    naming 0.139 contradicts the corrected figure now carried in
    fastapi_routes.py, route_integration.py, server_discovery.py, mesh/a2a.py,
    test_route_include_router_1396.py and the v3.3.2 release notes."""
    text = CI_WORKFLOW.read_text()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if "include_router" not in line:
            continue
        stale = re.findall(r"0\.1(?:38|39|40)(?:\.\d+)?", line)
        assert not stale, (
            f"{CI_WORKFLOW.name}:{lineno} attributes the include_router change "
            f"to {stale}; it landed in 0.137.0: {line.strip()!r}"
        )


if __name__ == "__main__":
    import tempfile

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        # ci.yml runs this file directly as well as under pytest, so the
        # __main__ runner has to supply pytest's `tmp_path` fixture itself.
        if fn.__code__.co_argcount:
            with tempfile.TemporaryDirectory() as d:
                fn(pathlib.Path(d))
        else:
            fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed")
