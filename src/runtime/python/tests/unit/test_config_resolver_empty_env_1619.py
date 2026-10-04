"""Issue #1619: a set-but-empty env var means "unset".

``FOO=`` is a routine outcome (empty Helm value, ``docker run -e FOO``,
``export FOO="$UNSET"``). It must fall through to the override and then the
default instead of shadowing them (and, for validated rules, logging a
validation error). Whitespace-only follows the Rust core: unset for validated
rules, kept for ``STRING_RULE``.
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


class TestStringRuleMatchesRustCore:
    """STRING_RULE mirrors the Rust string resolver: ``""`` is unset, a
    whitespace-only value is kept."""

    def test_empty_falls_through_to_override(self, monkeypatch):
        monkeypatch.setenv(ENV, "")
        assert get_config_value(ENV, override="o", default="d") == "o"

    def test_empty_falls_through_to_default(self, monkeypatch):
        monkeypatch.setenv(ENV, "")
        assert get_config_value(ENV, default="d") == "d"

    def test_empty_without_default_is_none(self, monkeypatch):
        monkeypatch.setenv(ENV, "")
        assert get_config_value(ENV) is None

    def test_whitespace_is_kept(self, monkeypatch):
        monkeypatch.setenv(ENV, "   ")
        assert get_config_value(ENV, override="o", default="d") == "   "

    def test_python_path_agrees_with_rust_path(self, monkeypatch):
        # MCP_MESH_NAMESPACE resolves through the Rust core when available;
        # the Python fallback must give the same answers.
        if not config_resolver._RUST_CORE_AVAILABLE:
            pytest.skip("mcp_mesh_core not available")
        for value in ("", "   "):
            monkeypatch.setenv("MCP_MESH_NAMESPACE", value)
            monkeypatch.setenv(ENV, value)
            rust = get_config_value("MCP_MESH_NAMESPACE", override="o", default="d")
            python = get_config_value(ENV, override="o", default="d")
            assert rust == python, f"value={value!r}: rust={rust!r} python={python!r}"


class TestSurroundingWhitespaceIsIgnored:
    """Rust core and TS strip set values before parsing; Python matches."""

    @pytest.mark.parametrize(
        "value,expected",
        [(" true ", True), ("\tON\n", True), (" 0 ", False), ("  off", False)],
    )
    def test_truthy(self, monkeypatch, caplog, value, expected):
        monkeypatch.setenv(ENV, value)
        with caplog.at_level(logging.ERROR, logger=config_resolver.__name__):
            result = get_config_value(
                ENV, default=not expected, rule=ValidationRule.TRUTHY_RULE
            )
        assert result is expected
        assert not caplog.records

    def test_truthy_override_string(self, monkeypatch):
        monkeypatch.delenv(ENV, raising=False)
        assert (
            get_config_value(
                ENV, override=" yes ", default=False, rule=ValidationRule.TRUTHY_RULE
            )
            is True
        )

    @pytest.mark.parametrize(
        "rule,value,expected",
        [
            (ValidationRule.NONZERO_RULE, " 7 ", 7),
            (ValidationRule.PORT_RULE, "\t9090\n", 9090),
            (ValidationRule.FLOAT_RULE, " 2.5 ", 2.5),
        ],
        ids=["nonzero", "port", "float"],
    )
    def test_numeric(self, monkeypatch, rule, value, expected):
        monkeypatch.setenv(ENV, value)
        assert get_config_value(ENV, default=1, rule=rule) == expected


class TestMeshLlmModel:
    """MESH_LLM_MODEL: whitespace-only means unset, as in the TS SDK."""

    @pytest.mark.parametrize("value", ["", "   ", None], ids=["empty", "ws", "absent"])
    def test_blank_falls_through_to_model_kwarg(self, monkeypatch, value):
        from mesh.decorators import _resolve_llm_model

        if value is None:
            monkeypatch.delenv("MESH_LLM_MODEL", raising=False)
        else:
            monkeypatch.setenv("MESH_LLM_MODEL", value)
        assert _resolve_llm_model("anthropic/claude") == "anthropic/claude"
        assert _resolve_llm_model(None) is None

    def test_set_value_wins_and_is_trimmed(self, monkeypatch):
        from mesh.decorators import _resolve_llm_model

        monkeypatch.setenv("MESH_LLM_MODEL", " openai/gpt-4o ")
        assert _resolve_llm_model("anthropic/claude") == "openai/gpt-4o"
