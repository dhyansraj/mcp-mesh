"""Issue #1619: a set-but-empty env var means "unset" for validated rules.

``FOO=`` is a routine outcome (empty Helm value, ``docker run -e FOO``,
``export FOO="$UNSET"``). For every rule except ``STRING_RULE`` the empty
value can never validate, so it must fall through to the override and then
the default instead of shadowing them and logging a validation error.
"""

import logging

import pytest

from _mcp_mesh.shared import config_resolver
from _mcp_mesh.shared.config_resolver import ValidationRule, get_config_value

ENV = "MCP_MESH_TEST_1619_KNOB"  # not a Rust-core key: exercises the Python path

# rule -> (override, default)
VALIDATED_RULES = {
    ValidationRule.TRUTHY_RULE: (False, True),
    ValidationRule.NONZERO_RULE: (7, 5),
    ValidationRule.PORT_RULE: (9090, 8080),
    ValidationRule.FLOAT_RULE: (2.5, 1.5),
    ValidationRule.URL_RULE: ("http://override:1", "http://default:1"),
}

EMPTY_VALUES = {"empty": "", "whitespace": "   ", "absent": None}


@pytest.fixture
def set_env(monkeypatch):
    def _set(value):
        if value is None:
            monkeypatch.delenv(ENV, raising=False)
        else:
            monkeypatch.setenv(ENV, value)

    return _set


@pytest.mark.parametrize("value", EMPTY_VALUES.values(), ids=EMPTY_VALUES.keys())
@pytest.mark.parametrize("rule", VALIDATED_RULES, ids=lambda r: r.name)
class TestEmptyEnvIsUnset:
    def test_default_applies(self, set_env, caplog, rule, value):
        override, default = VALIDATED_RULES[rule]
        set_env(value)
        with caplog.at_level(logging.ERROR, logger=config_resolver.__name__):
            result = get_config_value(ENV, default=default, rule=rule)
        assert result == default
        assert not caplog.records, "empty env must not log a validation error"

    def test_override_applies(self, set_env, rule, value):
        override, default = VALIDATED_RULES[rule]
        set_env(value)
        assert get_config_value(ENV, override=override, default=default, rule=rule) == (
            override
        )

    def test_no_default_resolves_to_none(self, set_env, rule, value):
        set_env(value)
        assert get_config_value(ENV, rule=rule) is None

    def test_invalid_default_does_not_raise(self, set_env, rule, value):
        # Previously: '' failed validation, then the (invalid) default did
        # too, and get_config_value raised ConfigResolutionError.
        set_env(value)
        assert get_config_value(ENV, default="DEFAULT", rule=rule) is None


@pytest.mark.parametrize("rule", VALIDATED_RULES, ids=lambda r: r.name)
def test_non_empty_invalid_value_still_rejected(monkeypatch, caplog, rule):
    _, default = VALIDATED_RULES[rule]
    monkeypatch.setenv(ENV, "not-a-valid-value")
    with caplog.at_level(logging.ERROR, logger=config_resolver.__name__):
        assert get_config_value(ENV, default=default, rule=rule) == default
    assert caplog.records, "a genuinely invalid value must still be reported"


def test_set_value_still_wins_over_override(monkeypatch):
    monkeypatch.setenv(ENV, "off")
    assert (
        get_config_value(
            ENV, override=True, default=True, rule=ValidationRule.TRUTHY_RULE
        )
        is False
    )


@pytest.mark.parametrize("value", ["", "   "], ids=["empty", "whitespace"])
def test_string_rule_keeps_empty_value(monkeypatch, value):
    # An empty string is a valid STRING_RULE value; it is not treated as unset.
    monkeypatch.setenv(ENV, value)
    assert get_config_value(ENV, override="o", default="d") == value
