# Llama Stack on OpenShift (MiniMax + MCP)

All resources in this overlay use the OpenShift/Kubernetes namespace **`agentic-demo`**.

Kubernetes/OpenShift manifests to run [Llama Stack](https://llamastack.github.io/) with:

- **Inference:** [MiniMax](https://www.minimax.io/) via the OpenAI-compatible API (`remote::openai`, provider id `minimax`).
- **Tools:** two external **MCP** servers (GitHub and OpenShift), configured as connectors. Llama Stack does not deploy those servers; you run them separately and point this stack at their HTTP/SSE endpoints.

The [Llama Stack Kubernetes Operator](https://github.com/llamastack/llama-stack-k8s-operator) reconciles a `LlamaStackDistribution` custom resource into a Deployment, Service, PVC, and related objects. This repository adds a Kustomize overlay, stack `config.yaml`, non-secret endpoint tuning, and an OpenShift `Route`.

## Prerequisites

1. **OpenShift cluster** with `oc` configured and permission to install operators or apply CRDs in your target namespace scope (cluster admins typically install the operator once per cluster).
2. **Llama Stack operator** installed, for example:

   ```bash
   oc apply -f https://github.com/llamastack/llama-stack-k8s-operator/releases/latest/download/operator.yaml
   ```

   Confirm the `LlamaStackDistribution` CRD exists: `oc get crd llamastackdistributions.llamastack.io`.

3. **MiniMax API key** from the [MiniMax platform](https://platform.minimax.io/).

4. **MCP servers** for GitHub and OpenShift reachable from the **`agentic-demo`** namespace (ClusterIP Services, or routes outside the cluster). Use the URL shape your server expects (often `…/sse` for SSE; some images use streamable HTTP on a different path).

## Repository layout

| Path | Purpose |
|------|---------|
| `openshift/kustomization.yaml` | Kustomize entrypoint: namespace, ConfigMaps, Secret, CR, Route; builds `llamastack-server-config` from `config/config.yaml`. |
| `openshift/config/config.yaml` | Llama Stack stack config (mounted as `/etc/llama-stack/config.yaml` in the pod). |
| `openshift/configmap-mcp-endpoints.yaml` | Non-secret values: `MCP_*_SSE_URL`, `MINIMAX_BASE_URL`. |
| `openshift/secret.yaml` | `minimax-api-key` (replace placeholder before apply, or manage the Secret out of band). |
| `openshift/llamastackdistribution.yaml` | `LlamaStackDistribution` CR (`starter` image, PVC under `/.llama`, env wiring). |
| `openshift/route.yaml` | Edge TLS `Route` to Service `llamastack-service:8321`. |
| `.gitignore` | Ignores local `_ref_*/` scratch directories. |

## Configure before deploy

1. **`openshift/secret.yaml`**  
   Set `stringData.minimax-api-key` to your real key. Prefer not committing secrets: create the Secret with `oc create secret generic llamastack-credentials --from-literal=minimax-api-key='…' -n agentic-demo` and remove `secret.yaml` from `kustomization.yaml` if you use that workflow.

2. **`openshift/configmap-mcp-endpoints.yaml`**  
   Replace the example URLs with the in-cluster DNS names (or external URLs) and ports for your GitHub and OpenShift MCP deployments. Paths must match each server’s transport (SSE vs other).

3. **Resources** (optional)  
   Edit `openshift/llamastackdistribution.yaml` `containerSpec.resources` and `storage.size` for your environment.

## Deploy

From the repository root:

```bash
oc apply -k openshift
```

Equivalent preview:

```bash
oc kustomize openshift
```

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
| CR not reconciling / no pods | Operator installed and watching your namespace; `oc describe llamastackdistribution llamastack -n agentic-demo`. |
| MCP tools missing or errors | MCP pods running; URLs in `llamastack-mcp-endpoints` correct; network policies allow egress from Llama Stack to MCP Services. |
| MiniMax auth errors | Secret key and `MINIMAX_BASE_URL`; MiniMax account and model access. |
| SQLite / disk errors | PVC bound; `SQLITE_STORE_DIR` matches writable path under `/.llama` (set in the CR). |

## References

- [Llama Stack Kubernetes Operator docs](https://llama-stack-k8s-operator.pages.dev/)
- [Llama Stack configuration / distributions](https://llamastack.github.io/docs/)
- [Llama Stack operator releases](https://github.com/llamastack/llama-stack-k8s-operator/releases)
