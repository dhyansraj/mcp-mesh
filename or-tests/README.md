# Tag-Level OR Test Agents

Test agents for Issue #471 Phase 4 - Tag-Level OR Alternatives.

## Syntax

Tag-level OR uses nested arrays in the `tags` field:

```python
dependencies=[
    {
        "capability": "math_operations",
        "tags": ["addition", ["python", "typescript"]],  # addition AND (python OR typescript)
    },
]
```

## Test Scenarios

### Scenario 1: Both providers available (prefers first alternative)

```bash
# Terminal 1: Start registry
meshctl -d --debug

# Terminal 2: Start Python math agent (port 9001)
source .venv/bin/activate
python or-tests/py-math-agent.py

# Terminal 3: Start TypeScript math agent (port 9002)
source .venv/bin/activate
python or-tests/ts-math-agent.py

# Terminal 4: Start calculator agent (port 9003)
source .venv/bin/activate
python or-tests/calculator-agent.py
```

Expected: Calculator resolves to py-math-agent (python is first OR alternative)

### Scenario 2: Only fallback available

```bash
# Terminal 1: Start registry
meshctl -d --debug

# Terminal 2: Start TypeScript math agent only (no Python agent)
source .venv/bin/activate
python or-tests/ts-math-agent.py

# Terminal 3: Start calculator agent
source .venv/bin/activate
python or-tests/calculator-agent.py
```

Expected: Calculator resolves to ts-math-agent (fallback used)

## Verification

Check resolution in registry:

```bash
meshctl list
meshctl deps calculator-agent
```

Or check via API:

```bash
curl http://localhost:8080/agents/calculator-agent | jq '.dependencies_resolved'
```
