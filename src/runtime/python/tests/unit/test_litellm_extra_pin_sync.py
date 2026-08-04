"""Guard the ``[litellm]`` extra as the sole install path for LiteLLM (#1383).

As of 3.5.0 ``litellm`` is NOT a base dependency. It is declared exactly once
per manifest, under ``[project.optional-dependencies] litellm``, and that entry
is the only thing that installs it — ``pip install mcp-mesh`` is slim and
big-3-native, ``pip install mcp-mesh[litellm]`` adds the long-tail provider
path that ``meshctl scaffold`` and ``mesh.helpers._require_litellm`` tell users
to pin.

Two things can silently break that contract:

  * litellm creeping back into ``[project] dependencies`` — the extra would
    still resolve, so nothing would fail, and every user would quietly get the
    ~30 MB tree back;
  * the two manifests drifting apart on the pin.

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
def test_litellm_is_not_a_base_dependency(rel: str) -> None:
    """``pip install mcp-mesh`` must stay slim (#1383)."""
    project = _load(rel)["project"]

    base = _requirements_named(project["dependencies"], "litellm")
    assert base == [], (
        f"{rel}: litellm is back in [project] dependencies as {base}. It was "
        "removed in 3.5.0 (#1383): the big-3 vendors dispatch through the "
        "bundled native SDK adapters and must not carry litellm's ~30 MB "
        "transitive tree. It belongs in the [litellm] extra only."
    )


@pytest.mark.parametrize("rel", sorted(_MANIFESTS))
def test_litellm_extra_declares_litellm_explicitly(rel: str) -> None:
    """The extra is the only thing that installs litellm, so it must say so."""
    project = _load(rel)["project"]
    extras = project["optional-dependencies"]

    assert "litellm" in extras, (
        f"{rel}: the [litellm] extra is missing. It is what "
        "'pip install mcp-mesh[litellm]' resolves against — the install "
        "guidance in mesh.helpers._require_litellm and the pin emitted by "
        "'meshctl scaffold' both name it."
    )

    extra = _requirements_named(extras["litellm"], "litellm")
    assert len(extra) == 1, (
        f"{rel}: the [litellm] extra must declare litellm exactly once, got "
        f"{extras['litellm']!r}. Nothing else installs litellm since 3.5.0, so "
        "an empty/stub extra resolves cleanly and installs nothing."
    )


def test_litellm_extra_pin_is_the_same_across_manifests() -> None:
    """The published manifest and the source manifest must agree on litellm.

    They deliberately differ on upper bounds for some other deps, but litellm
    is one pin: a user installing ``mcp-mesh[litellm]`` from PyPI and a
    contributor installing the source tree editable must get the same
    long-tail provider path.
    """
    pins = {}
    for rel in _MANIFESTS:
        project = _load(rel)["project"]
        pins[rel] = _requirements_named(
            project["optional-dependencies"]["litellm"], "litellm"
        )[0]

    assert len(set(pins.values())) == 1, (
        f"the [litellm] extra pin diverges across manifests: {pins}\n"
        "Both must be updated together — otherwise 'mcp-mesh[litellm]' means "
        "one thing from PyPI and another from a source checkout."
    )
