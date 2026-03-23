# Llama Stack on OpenShift (MiniMax + MCP)

All resources in this overlay use the OpenShift/Kubernetes namespace **`agentic-demo`**.

Kubernetes/OpenShift manifests to run [Llama Stack](https://llamastack.github.io/) with:

- **Inference:** [MiniMax](https://www.minimax.io/) via the OpenAI-compatible API (`remote::openai`, provider id `minimax`).
- **Tools:** MCP connectors for **GitHub** and **OpenShift**. This repo includes an optional in-cluster **GitHub MCP** Deployment (official `ghcr.io/github/github-mcp-server` in HTTP mode plus an nginx sidecar that injects a PAT from a **Secret**). You still supply your **OpenShift / Kubernetes MCP** endpoint separately in `configmap-mcp-endpoints.yaml`.

The [Llama Stack Kubernetes Operator](https://github.com/llamastack/llama-stack-k8s-operator) reconciles a `LlamaStackDistribution` custom resource into a Deployment, Service, PVC, and related objects. This repository adds a Kustomize overlay, stack `config.yaml`, non-secret endpoint tuning, and an OpenShift `Route`.

## Prerequisites

1. **OpenShift cluster** with `oc` configured and permission to install operators or apply CRDs in your target namespace scope (cluster admins typically install the operator once per cluster).
2. **Llama Stack operator** installed, for example:

   ```bash
   oc apply -f https://github.com/llamastack/llama-stack-k8s-operator/releases/latest/download/operator.yaml
   ```

   Confirm the `LlamaStackDistribution` CRD exists: `oc get crd llamastackdistributions.llamastack.io`.

3. **MiniMax API key** from the [MiniMax platform](https://platform.minimax.io/).

4. **GitHub PAT** if you use the bundled GitHub MCP manifests: create or edit Secret `github-mcp-pat` (see below). For the second connector, ensure your OpenShift/Kubernetes MCP Service is reachable from **`agentic-demo`** and that `MCP_OPENSHIFT_SSE_URL` matches its URL (path depends on that server’s transport).

## Repository layout

| Path | Purpose |
|------|---------|
| `openshift/kustomization.yaml` | Kustomize entrypoint: namespace, ConfigMaps, Secret, CR, Route; builds `llamastack-server-config` from `config/config.yaml`. |
| `openshift/config/config.yaml` | Llama Stack stack config (mounted as `/etc/llama-stack/config.yaml` in the pod). |
| `openshift/github-mcp-secret.yaml` | GitHub PAT for the in-cluster GitHub MCP proxy (`GITHUB_PERSONAL_ACCESS_TOKEN`). |
| `openshift/github-mcp.yaml` | `Deployment` (github-mcp-server `http` + nginx injecting `Authorization`), `Service` `github-mcp:8080`, nginx `ConfigMap`. |
| `openshift/configmap-mcp-endpoints.yaml` | Non-secret values: `MCP_*` connector base URLs, `MINIMAX_BASE_URL`. |
| `openshift/secret.yaml` | MiniMax `minimax-api-key` (replace placeholder before apply, or manage the Secret out of band). |
| `openshift/llamastackdistribution.yaml` | `LlamaStackDistribution` CR (`starter` image, PVC under `/.llama`, env wiring). |
| `openshift/route.yaml` | Edge TLS `Route` to Service `llamastack-service:8321`. |
| `.gitignore` | Ignores local `_ref_*/` scratch directories. |

## Configure before deploy

1. **`openshift/secret.yaml`**  
   Set `stringData.minimax-api-key` to your real key. Prefer not committing secrets: create the Secret with `oc create secret generic llamastack-credentials --from-literal=minimax-api-key='…' -n agentic-demo` and remove `secret.yaml` from `kustomization.yaml` if you use that workflow.

2. **`openshift/github-mcp-secret.yaml`**  
   Set `stringData.GITHUB_PERSONAL_ACCESS_TOKEN` to a [GitHub PAT](https://github.com/settings/personal-access-tokens/new) with the scopes your toolsets need. The [GitHub MCP Server](https://github.com/github/github-mcp-server) documents classic vs fine-grained tokens and scope filtering.  
   **Why a Secret:** the container image’s **HTTP** mode expects `Authorization: Bearer …` on each MCP request (unlike **stdio** mode, which uses the `GITHUB_PERSONAL_ACCESS_TOKEN` environment variable inside a single local process). Llama Stack’s connector config only stores a URL, not a GitHub token, so this repo uses an **nginx sidecar** that adds the `Authorization` header using the value from Secret `github-mcp-pat`. Llama Stack calls `http://github-mcp…:8080/` with no GitHub credentials; only workloads that can reach that `Service` can trigger GitHub API usage as that PAT—treat it as sensitive and use `NetworkPolicy` if required.

3. **`openshift/configmap-mcp-endpoints.yaml`**  
   The default `MCP_GITHUB_SSE_URL` targets the bundled `github-mcp` Service (streamable HTTP at `/`). Adjust `MCP_OPENSHIFT_SSE_URL` for your other MCP server.

4. **Resources** (optional)  
   Edit `openshift/llamastackdistribution.yaml` `containerSpec.resources` and `storage.size` for your environment.

### Alternatives (no in-cluster GitHub MCP)

- Remove `github-mcp-secret.yaml` and `github-mcp.yaml` from `kustomization.yaml` and point `MCP_GITHUB_SSE_URL` at your own deployment or at GitHub’s **remote** MCP URL; if the server requires a Bearer token on the wire, you must either supply auth on Llama Stack client calls where the product supports it, or keep a small proxy like the nginx pattern above.
- For **stdio-only** GitHub MCP (Docker on a laptop), the PAT is typically passed as **`GITHUB_PERSONAL_ACCESS_TOKEN`** on the MCP **server** process— that pattern does not apply to Llama Stack’s HTTP connector unless you add a bridge/proxy.

## Deploy

From the repository root, `-k` is the path to the directory that contains `kustomization.yaml` (here, the `openshift/` folder — not an OpenShift-specific flag).

```bash
oc apply -k openshift
```

Equivalent preview:

```bash
oc kustomize openshift
```

If you are already inside `openshift/`, use `oc apply -k .` instead.

The operator creates a Service named **`llamastack-service`** (for CR `metadata.name: llamastack`). The Route targets port name **`http`**.

## Verify

```bash
oc get llamastackdistribution -n agentic-demo
oc get pods,svc,route -n agentic-demo
oc logs -n agentic-demo -l app=llama-stack --tail=100
```

When ready, obtain the public URL:

```bash
oc get route llamastack -n agentic-demo -o jsonpath='{.spec.host}{"\n"}'
```

The Llama Stack HTTP API listens on port **8321** inside the cluster. OpenAI-compatible clients typically use `https://<route-host>/v1` (see [OpenAI compatibility](https://llamastack.github.io/docs/providers/openai)).

Use a MiniMax model id in requests (for example `MiniMax-M2.7`); see [MiniMax OpenAI-compatible API](https://platform.minimax.io/docs/api-reference/text-openai-api.md).

## OpenShift notes

- **Image pulls:** If your cluster cannot pull `docker.io/llamastack/distribution-starter`, mirror the image or add pull secrets and adjust the operator or distribution image settings per your org’s policy.
- **Security context / SCC:** If the pod fails to start with permission errors, work with your cluster admin on the appropriate SCC and ServiceAccount (the operator creates a per-CR ServiceAccount by default).
- **TLS:** The sample Route uses **edge** termination. For re-encrypt or passthrough, change `openshift/route.yaml` accordingly.
- **Config updates:** Changing `openshift/config/config.yaml` and re-applying updates the generated ConfigMap; the operator’s ConfigMap hash annotation should roll the Deployment. If not, delete the pod to force a restart.

## Troubleshooting

| Symptom | Things to check |
|--------|------------------|
| `Distribution name not supported` (e.g. for `starter`) | The operator only accepts `spec.server.distribution.name` values baked into its embedded `distributions.json`. Older or custom builds may omit `starter`. This repo uses **`distribution.image`** (`docker.io/llamastack/distribution-starter:latest`) so reconciliation does not depend on that list. Alternatively upgrade the [operator](https://github.com/llamastack/llama-stack-k8s-operator/releases) to a release whose embedded distributions include `starter`, then you may switch to `name: starter` and remove `image`. |
| CR not reconciling / no pods | Operator installed and watching your namespace; `oc describe llamastackdistribution llamastack -n agentic-demo`. |
| MCP tools missing or errors | MCP pods running; URLs in `llamastack-mcp-endpoints` correct; network policies allow egress from Llama Stack to MCP Services. |
| MiniMax auth errors | Secret key and `MINIMAX_BASE_URL`; MiniMax account and model access. |
| SQLite / disk errors | PVC bound; `SQLITE_STORE_DIR` matches writable path under `/.llama` (set in the CR). |

## References

- [Llama Stack Kubernetes Operator docs](https://llama-stack-k8s-operator.pages.dev/)
- [Llama Stack configuration / distributions](https://llamastack.github.io/docs/)
- [Llama Stack operator releases](https://github.com/llamastack/llama-stack-k8s-operator/releases)
