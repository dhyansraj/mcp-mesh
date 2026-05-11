package scaffold

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestSanitizeIdentifier(t *testing.T) {
	cases := map[string]string{
		"get-date":    "get_date",     // hyphen -> underscore
		"123-get-date": "_123_get_date", // digit-prefix gets _
		"tool@v2":     "tool_v2",      // special char -> underscore
		"":            "skill",        // empty fallback
		"1":           "_1",           // pure digit
		"valid_name":  "valid_name",   // no-op
		"1day-forecast": "_1day_forecast",
		"with space":  "with_space",
	}
	for in, want := range cases {
		t.Run(in, func(t *testing.T) {
			assert.Equal(t, want, sanitizeIdentifier(in))
		})
	}
}

func TestSanitizeIdentifier_StripsUnicode(t *testing.T) {
	// Multi-byte runes outside [A-Za-z0-9_] each become one underscore.
	got := sanitizeIdentifier("hot")
	assert.Equal(t, "hot", got)

	// All-special input collapses to underscores; first char is still '_'
	// (not a digit), so no extra prefix is added.
	got = sanitizeIdentifier("@@@")
	assert.Equal(t, "___", got)
}

func TestValidateA2AConsumerContext_RejectsTraversalPackage(t *testing.T) {
	ctx := &ScaffoldContext{
		Name:        "bridge",
		Language:    "java",
		OutputDir:   ".",
		Port:        8080,
		AgentType:   "a2a-consumer",
		Template:    "a2a-consumer",
		JavaPackage: "../../tmp.evil",
	}
	err := validateA2AConsumerContext(ctx)
	if assert.Error(t, err) {
		assert.Contains(t, err.Error(), "valid Java package identifier")
	}
}

func TestValidateA2AConsumerContext_AcceptsValidPackage(t *testing.T) {
	ctx := &ScaffoldContext{
		Name:        "bridge",
		Language:    "java",
		OutputDir:   ".",
		Port:        8080,
		AgentType:   "a2a-consumer",
		Template:    "a2a-consumer",
		JavaPackage: "com.example.bridge",
	}
	assert.NoError(t, validateA2AConsumerContext(ctx))
}

func TestValidateA2AConsumerContext_RejectsUppercasePackage(t *testing.T) {
	ctx := &ScaffoldContext{
		Name:        "bridge",
		Language:    "java",
		OutputDir:   ".",
		Port:        8080,
		AgentType:   "a2a-consumer",
		Template:    "a2a-consumer",
		JavaPackage: "Com.Example.Bridge",
	}
	err := validateA2AConsumerContext(ctx)
	if assert.Error(t, err) {
		assert.Contains(t, err.Error(), "valid Java package identifier")
	}
}

func TestValidateA2AConsumerContext_DefaultsJavaPackage(t *testing.T) {
	ctx := &ScaffoldContext{
		Name:      "my-bridge",
		Language:  "java",
		OutputDir: ".",
		Port:      8080,
		AgentType: "a2a-consumer",
		Template:  "a2a-consumer",
	}
	assert.NoError(t, validateA2AConsumerContext(ctx))
	assert.Equal(t, "com.example.mybridge", ctx.JavaPackage)
}

func TestBuildScaffoldSkills_SanitizesDigitPrefixID(t *testing.T) {
	card := &AgentCard{
		Skills: []CardSkill{
			{ID: "123-get-date", Name: "Get Date"},
		},
	}
	skills := buildScaffoldSkills(card)
	if assert.Len(t, skills, 1) {
		// Original ID preserved for capability/skill-id wiring.
		assert.Equal(t, "123-get-date", skills[0].ID)
		assert.Equal(t, "123-get-date", skills[0].Capability)
		// Function/class/method names must be valid identifiers
		// (must not start with a digit).
		assert.Equal(t, "_123_get_date", skills[0].FunctionName)
		assert.NotEmpty(t, skills[0].ClassName)
		assert.NotEmpty(t, skills[0].MethodName)
		for _, name := range []string{skills[0].FunctionName, skills[0].ClassName, skills[0].MethodName} {
			first := name[0]
			assert.False(t, first >= '0' && first <= '9',
				"identifier must not start with digit: %q", name)
		}
	}
}

func TestBuildScaffoldSkills_SanitizesSpecialChars(t *testing.T) {
	card := &AgentCard{
		Skills: []CardSkill{
			{ID: "tool@v2", Name: "Tool"},
		},
	}
	skills := buildScaffoldSkills(card)
	if assert.Len(t, skills, 1) {
		assert.Equal(t, "tool_v2", skills[0].FunctionName)
	}
}

func TestBuildScaffoldSkills_OfflinePlaceholder(t *testing.T) {
	skills := buildScaffoldSkills(nil)
	if assert.Len(t, skills, 1) {
		assert.Equal(t, "todo_skill", skills[0].FunctionName)
	}
}
