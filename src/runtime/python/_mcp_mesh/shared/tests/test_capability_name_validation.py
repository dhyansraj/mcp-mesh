"""RFC #1280 v3: dot-namespacing for capability names.

`AgentCapability.name` accepts one or more dot-separated segments, each following
the flat rule (letter-led, alnum/underscore/hyphen). This strictly widens the old
single-segment pattern (every previously-valid flat name still validates) and
forbids leading/trailing/consecutive dots. MUST stay in lock-step with the Go
registry's capabilityNamePattern (src/core/registry/validation.go).
"""

import pytest

from _mcp_mesh.shared.support_types import AgentCapability


@pytest.mark.parametrize(
    "name",
    [
        "greeting",  # existing flat name still valid
        "smart_greet",  # underscore
        "weather-report",  # hyphen
        "a",  # single letter
        "media.caption",  # two segments
        "a.b",  # minimal dotted
        "a.b.c",  # three segments
        "llm.chat",  # phase-1/2 dotted dependency style
        "a1.b2_c-3",  # digits/underscore/hyphen within segments
    ],
)
def test_valid_capability_names(name):
    assert AgentCapability(name=name).name == name


@pytest.mark.parametrize(
    "name",
    [
        "",  # empty
        ".a",  # leading dot
        "a.",  # trailing dot
        "a..b",  # consecutive dots
        "a.-b",  # segment must start with a letter
        "1a.b",  # must start with a letter
        "a.1b",  # second segment must start with a letter
        ".",  # just a dot
        "a.b.",  # trailing dot after multiple segments
        "a b",  # space
        "a.b\n",  # trailing newline (fullmatch, not match, rejects this)
    ],
)
def test_invalid_capability_names(name):
    with pytest.raises(ValueError):
        AgentCapability(name=name)
