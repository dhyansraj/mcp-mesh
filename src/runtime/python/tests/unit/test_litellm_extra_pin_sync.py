"""Guard the deliberately-duplicated ``litellm`` pin (issue #1383).

``litellm`` is declared twice in each Python manifest:

  * in ``[project] dependencies``  — it is still a BASE dependency today, so
    nothing breaks for existing installs;
  * in ``[project.optional-dependencies] litellm`` — the forward-compatible
    opt-in extra that ``meshctl scaffold`` and
    ``mesh.helpers._require_litellm`` tell users to pin.

The duplication is intentional (see the comments in both manifests), but a
version bump or a new upstream exclusion applied to only one of the two would
silently change what ``mcp-mesh[litellm]`` resolves to versus ``mcp-mesh``.
These checks fail loudly on that drift.

Both manifests are checked because ``packaging/pypi/pyproject.toml`` is the one
PyPI publishes and ``src/runtime/python/pyproject.toml`` is the one editable /
source installs use — a user hitting the extra from either direction must get
the same litellm.
"""

import pathlib
import tomllib

import pytest

# tests/unit/ -> tests/ -> python/ -> runtime/ -> src/ -> <repo root>
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]

_MANIFESTS = {
    "packaging/pypi/pyproject.toml": _REPO_ROOT / "packaging/pypi/pyproject.toml",
    "src/runtime/python/pyproject.toml": (
        _REPO_ROOT / "src/runtime/python/pyproject.toml"
    ),
}


def _load(rel: str) -> dict:
    path = _MANIFESTS[rel]
    if not path.is_file():
        # Running from an installed wheel/sdist rather than a source checkout.
        pytest.skip(f"{rel} not present (not a source checkout)")
    return tomllib.loads(path.read_text())


def _requirements_named(reqs: list[str], name: str) -> list[str]:
    """Return every requirement string in ``reqs`` whose project name is
    ``name`` (matched on the leading identifier, before any extras/specifier)."""
    hits = []
    for req in reqs:
        head = req.split(";")[0].strip()
        ident = ""
        for ch in head:
            if ch.isalnum() or ch in "-_.":
                ident += ch
            else:
                break
        if ident.lower().replace("_", "-") == name:
            hits.append(head)
    return hits


@pytest.mark.parametrize("rel", sorted(_MANIFESTS))
def test_litellm_extra_pin_matches_base_pin(rel: str) -> None:
    """The ``[litellm]`` extra must restate the base pin verbatim."""
    data = _load(rel)
    project = data["project"]

    base = _requirements_named(project["dependencies"], "litellm")
    assert len(base) == 1, f"{rel}: expected exactly one base litellm pin, got {base}"

    extras = project["optional-dependencies"]
    assert "litellm" in extras, (
        f"{rel}: the [litellm] extra is missing. It is what "
        "'pip install mcp-mesh[litellm]' resolves against — the install "
        "guidance in mesh.helpers._require_litellm and the pin emitted by "
        "'meshctl scaffold' both name it."
    )

    extra = _requirements_named(extras["litellm"], "litellm")
    assert len(extra) == 1, (
        f"{rel}: the [litellm] extra must declare litellm explicitly, got "
        f"{extras['litellm']!r}. An empty/stub extra resolves cleanly today "
        "(litellm is still a base dependency) but would silently install "
        "nothing once the base entry is removed."
    )

    assert extra[0] == base[0], (
        f"{rel}: the [litellm] extra pin drifted from the base pin.\n"
        f"  base : {base[0]}\n"
        f"  extra: {extra[0]}\n"
        "Both must be updated together — otherwise 'mcp-mesh[litellm]' and "
        "'mcp-mesh' resolve to different litellm versions."
    )


def test_litellm_pin_is_the_same_across_manifests() -> None:
    """The published manifest and the source manifest must agree on litellm.

    They deliberately differ on upper bounds for some other deps, but litellm
    is one pin: a user installing from PyPI and a contributor installing the
    source tree editable must get the same long-tail provider path.
    """
    pins = {}
    for rel in _MANIFESTS:
        project = _load(rel)["project"]
        pins[rel] = (
            _requirements_named(project["dependencies"], "litellm")[0],
            _requirements_named(project["optional-dependencies"]["litellm"], "litellm")[
                0
            ],
        )

    values = list(pins.values())
    assert len(set(values)) == 1, f"litellm pins diverge across manifests: {pins}"
