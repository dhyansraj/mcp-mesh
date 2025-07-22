# Agent Code Deployment Methods

The mcp-mesh-agent chart supports three different methods for deploying Python agent scripts. Each method has different use cases and trade-offs.

## Method Comparison

| Method       | Script Source    | ConfigMap | Complexity  | Flexibility | Best For    |
| ------------ | ---------------- | --------- | ----------- | ----------- | ----------- |
| **Built-in** | Container Image  | ❌ None   | ⭐ Simple   | ⭐ Static   | Production  |
| **External** | Manual ConfigMap | ✋ Manual | ⭐⭐ Medium | ⭐⭐⭐ High | Advanced    |
| **Auto-Gen** | Chart Template   | ✅ Auto   | ⭐ Simple   | ⭐⭐ Medium | Development |

## Method 1: Built-in Script (Container Image)

### Configuration

```yaml
agent:
  script: "/app/agents/hello_world.py"
```

### Deployment

```bash
helm install my-agent ./helm/mcp-mesh-agent \
  --set agent.script=/app/agents/hello_world.py \
  --set registry.url=http://mcp-mesh-registry:8080
```

### Pros

- ✅ **Simplest configuration** - single parameter
- ✅ **Immutable deployments** - script is part of container
- ✅ **No external dependencies** - self-contained
- ✅ **Production ready** - follows container best practices

### Cons

- ❌ **Requires image rebuild** for script changes
- ❌ **Less flexible** - script is baked into image
- ❌ **Slower iteration** - build → push → deploy cycle

### Use Cases

- Production deployments
- Immutable infrastructure
- CI/CD pipelines
- Pre-packaged agents

## Method 2: External ConfigMap

### Configuration

```yaml
agentCode:
  enabled: true
  configMapName: "my-agent-code"
  mountPath: "/app"
```

### Deployment

```bash
# Create ConfigMap manually
kubectl create configmap my-agent-code --from-file=agent.py=./my-agent.py

# Deploy with external ConfigMap
helm install my-agent ./helm/mcp-mesh-agent \
  --set agentCode.enabled=true \
  --set agentCode.configMapName=my-agent-code \
  --set registry.url=http://mcp-mesh-registry:8080
```

### Pros

- ✅ **Maximum flexibility** - complete control over ConfigMap
- ✅ **Independent updates** - ConfigMap managed separately
- ✅ **Multiple sources** - can be created from various tools
- ✅ **Advanced scenarios** - custom labels, annotations, etc.

### Cons

- ❌ **Manual management** - requires separate ConfigMap creation
- ❌ **More complex** - two-step deployment process
- ❌ **Coordination needed** - ensure ConfigMap exists before deployment

### Use Cases

- GitOps workflows
- External configuration management
- Advanced ConfigMap requirements
- Multi-environment deployments

## Method 3: Auto-Generated ConfigMap (Recommended)

### Configuration

```yaml
agentCode:
  enabled: true
  scriptPath: "scripts/my-agent.py"
  mountPath: "/app"
```

### Deployment

```bash
# Single command - ConfigMap generated automatically, agent name from script
helm install my-agent ./helm/mcp-mesh-agent \
  --set agentCode.enabled=true \
  --set agentCode.scriptPath=scripts/my-agent.py \
  --set registry.url=http://mcp-mesh-registry:8080
```

### Pros

- ✅ **Simple deployment** - single command
- ✅ **Version controlled** - script is part of chart
- ✅ **Automatic ConfigMap** - no manual creation needed
- ✅ **Fast iteration** - easy to update scripts
- ✅ **Consistent naming** - auto-generated ConfigMap names
- ✅ **Script-driven naming** - agent name from @mesh.agent decorator

### Cons

- ❌ **Chart dependency** - script must be in chart directory
- ❌ **Limited customization** - uses standard ConfigMap template
- ❌ **Chart size** - scripts increase chart size

### Use Cases

- Development environments
- Quick prototyping
- Example deployments
- Tutorial scenarios

## Implementation Details

### Auto-Generated ConfigMap Template

```yaml
{{- if .Values.agentCode.enabled }}
{{- if .Values.agentCode.scriptPath }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "mcp-mesh-agent.fullname" . }}-code
data:
  agent.py: |
{{ .Files.Get .Values.agentCode.scriptPath | indent 4 }}
{{- end }}
{{- end }}
```

### Volume Mount Logic

```yaml
volumes:
  - name: agent-code
    configMap:
      name:
        {
          {
            .Values.agentCode.configMapName | default (printf "%s-code" (include "mcp-mesh-agent.fullname" .)),
          },
        }
      defaultMode: 0755
```

## Choosing the Right Method

### For Development

**Use Method 3 (Auto-Generated)** - fastest iteration, version controlled, simple deployment

### For Production

**Use Method 1 (Built-in)** - immutable, secure, follows container best practices

### For Advanced Use Cases

**Use Method 2 (External)** - maximum flexibility, external management, complex scenarios

## Migration Path

1. **Start with Method 3** for development and prototyping
2. **Move to Method 1** for production deployments
3. **Use Method 2** for advanced scenarios or GitOps workflows
