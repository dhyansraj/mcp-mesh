# Agent Code Deployment Methods

The mcp-mesh-agent chart runs a container image. There are two ways to get an
agent's code into it: bake it into an image of your own, or mount a single
Python script from a ConfigMap into the stock `mcpmesh/python-runtime` image.

## Method Comparison

| Method                  | Code Source     | Runs With                        | Best For                         |
| ----------------------- | --------------- | -------------------------------- | -------------------------------- |
| **Agent image**         | Container image | The image's own entrypoint/CMD   | Production, any language         |
| **External ConfigMap**  | ConfigMap       | `agent.command` on the stock image | Single-file Python, GitOps     |
| **Chart-rendered ConfigMap** | File in the chart directory | `agent.command` on the stock image | Local development with a chart copy |

## Method 1: Agent Image (recommended)

`meshctl scaffold` generates a Dockerfile (built on `mcpmesh/python-runtime`,
`mcpmesh/typescript-runtime` or `mcpmesh/java-runtime`) and a
`helm-values.yaml` for the agent. Build and push the image, then install the
chart with it:

```bash
meshctl scaffold basic --name my-agent
cd my-agent
docker buildx build --platform linux/amd64 -t myregistry/my-agent:v1.0.0 --push .

helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=myregistry/my-agent \
  --set image.tag=v1.0.0
```

The image's CMD starts the agent, so `agent.command` stays empty. The registry
is found at `<global.coreReleaseName>-mcp-mesh-registry:8000`
(`mcp-core-mcp-mesh-registry` by default); set `global.coreReleaseName` or
`registry.host` if core was installed under another release name.

### Pros

- Immutable deployments: the code is part of the image
- Works for every runtime, multi-file agents, and agents with extra packages
- Follows container best practices

### Cons

- Requires an image rebuild for code changes

## Method 2: External ConfigMap

For a single-file Python agent, mount the script into the stock runtime image.
The ConfigMap must hold the script under the key `agent.py`; it is mounted at
`agentCode.mountPath` (`/app/agent`), and `agent.command` runs it (the image's
entrypoint is `python` with no script, so the command is required).

```bash
kubectl create configmap my-agent-code -n mcp-mesh \
  --from-file=agent.py=./my_agent.py

helm install my-agent ./helm/mcp-mesh-agent -n mcp-mesh \
  --set agentCode.enabled=true \
  --set agentCode.configMapName=my-agent-code \
  --set 'agent.command={python,/app/agent/agent.py}'
```

### Pros

- No image build for a one-file agent
- The ConfigMap can be managed independently (GitOps, Kustomize)

### Cons

- Python only, single file, and only packages the runtime image already has
- Two-step deployment: the ConfigMap must exist before the pod starts

## Method 3: Chart-Rendered ConfigMap

With a local copy of the chart, the chart can render the ConfigMap itself from
a file inside the chart directory (`agentCode.scriptPath` is read with Helm's
`.Files.Get`, so it cannot point outside the chart, and it does not work with
the published OCI chart):

```bash
helm install my-agent ./helm/mcp-mesh-agent -n mcp-mesh \
  --set agentCode.enabled=true \
  --set agentCode.scriptPath=scripts/demo-agent.py \
  --set 'agent.command={python,/app/agent/agent.py}'
```

The rendered ConfigMap is named `<fullname>-code` and holds the script under
`agent.py`. See [examples/auto-configmap-values.yaml](../examples/auto-configmap-values.yaml).

### Pros

- Single command; the script is versioned with your chart copy

### Cons

- Requires a forked or vendored chart
- Same limits as Method 2

## Choosing a Method

- **Production, or any non-Python agent:** Method 1.
- **A quick single-file Python agent:** Method 2.
- **Iterating on a script inside a local chart checkout:** Method 3.
