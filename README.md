# Llama Stack on OpenShift (vLLM + MCP)

All resources in this overlay use the OpenShift/Kubernetes namespace **`agentic-demo`**.

Kubernetes/OpenShift manifests to run [Llama Stack](https://llamastack.github.io/) with:

- **Inference:** [vLLM](https://github.com/vllm-project/vllm) on the cluster (`remote::vllm`, provider id **`vllm`**), OpenAI-compatible **`/v1`**. The sample config assumes you serve **MiniMax-family** (or other) weights from that vLLM instance—not the MiniMax cloud API.
- **Tools:** MCP connectors for **GitHub** and **OpenShift / Kubernetes**. This repo deploys both in-cluster: **GitHub MCP** (`ghcr.io/github/github-mcp-server` in HTTP mode plus an nginx sidecar that injects a PAT from a **Secret**) and **Kubernetes MCP** (`quay.io/mcp-servers/kubernetes-mcp-server` with a namespace-scoped `ServiceAccount` and read-only `Role`). Override either endpoint in `configmap-mcp-endpoints.yaml` if you use external MCP servers.

The [Red Hat OpenShift AI Llama Stack Operator](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html-single/working_with_llama_stack/) reconciles a `LlamaStackDistribution` custom resource into a Deployment, Service, PVC, and related objects. This repository adds a Kustomize overlay, stack `config.yaml`, non-secret endpoint tuning, and an OpenShift **Route** for the API.

## Prerequisites

1. **Red Hat OpenShift AI (RHOAI)** installed on the cluster (Operator Lifecycle Manager subscription to `rhods-operator`). Cluster admins install this once per cluster—see [Installing OpenShift AI](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/installing_and_uninstalling_openshift_ai_self-managed/installing-and-deploying-openshift-ai_install).

2. **Llama Stack operator** enabled via the `DataScienceCluster` CR (managed by RHOAI, not a separate upstream install):

   ```bash
   oc patch datasciencecluster default-dsc --type=merge \
     -p '{"spec":{"components":{"llamastackoperator":{"managementState":"Managed"}}}}'
   ```

   Replace `default-dsc` if your cluster uses a different `DataScienceCluster` name (`oc get datasciencecluster`).

   Verify the operator pod is **Running** in **`redhat-ods-applications`**:

   ```bash
   oc get pods -n redhat-ods-applications -l app.kubernetes.io/name=llama-stack-operator
   ```

   Confirm the `LlamaStackDistribution` CRD exists: `oc get crd llamastackdistributions.llamastack.io`.

   Do **not** install the upstream/community operator (`ogx-ai/ogx-k8s-operator` or `llamastack/llama-stack-k8s-operator` YAML)—it duplicates the RHOAI-managed operator and is unsupported on OpenShift AI clusters.

3. **vLLM** reachable from namespace **`agentic-demo`** (Service URL + port; OpenAI base URL must end with **`/v1`**). Optionally a bearer token if your vLLM is protected.

4. **GitHub PAT** if you use the bundled GitHub MCP manifests: create or edit Secret `github-mcp-pat` (see below).

5. **Kubernetes / OpenShift MCP** — `openshift/kubernetes-mcp.yaml` deploys **`quay.io/mcp-servers/kubernetes-mcp-server`** with a dedicated **`ServiceAccount`** and a namespace-scoped **read-only** `Role` (`get`, `list`, `watch` on core OpenShift/Kubernetes APIs plus **`tekton.dev`** for Tekton `PipelineRun` / `TaskRun` queries in **`agentic-demo`**). If MCP tools need **create/update/delete**, **cluster-scoped** reads (`Node`, `Namespace`, …), or other API groups, edit that `Role` (or switch to a `ClusterRole` + `ClusterRoleBinding` with care). For Llama Stack **connector** registration, set `MCP_OPENSHIFT_SSE_URL` to **`http://kubernetes-mcp:8080/sse`**. The bundled **call scripts** invoke tools via streamable HTTP at **`http://kubernetes-mcp:8080/mcp`** (same image, different transport).

## Repository layout

| Path | Purpose |
|------|---------|
| `openshift/kustomization.yaml` | Kustomize entrypoint: namespace, ConfigMaps, Secret, CR, Route; builds `llamastack-server-config` from `config/config.yaml`. |
| `openshift/config/config.yaml` | Llama Stack stack config (mounted as `/etc/llama-stack/config.yaml` in the pod). |
| `openshift/github-mcp-secret.yaml` | GitHub PAT for the in-cluster GitHub MCP proxy (`GITHUB_PERSONAL_ACCESS_TOKEN`). |
| `openshift/github-mcp.yaml` | `Deployment` (github-mcp-server `http` + nginx injecting `Authorization`), `Service` `github-mcp:8080`, nginx `ConfigMap`. |
| `openshift/kubernetes-mcp.yaml` | `Deployment` + `Service` **`kubernetes-mcp:8080`**, `ServiceAccount`, namespace **`Role`/`RoleBinding`** (read-only; includes **`tekton.dev`**). Connector URL **`/sse`**; call scripts use **`/mcp`**. |
| `openshift/configmap-mcp-endpoints.yaml` | Non-secret values: `MCP_*` connector base URLs, **`VLLM_URL`** (vLLM OpenAI base, e.g. `http://my-vllm:8000/v1`). |
| `openshift/secret.yaml` | Optional vLLM bearer token key **`vllm-api-token`** (many in-cluster servers accept `fake`). |
| `openshift/llamastackdistribution.yaml` | `LlamaStackDistribution` CR (RHOAI `odh-llama-stack-core-rhel9:v3.4`, PVC under `/.llama`, env wiring). |
| `openshift/route.yaml` | Edge TLS `Route` to Service `llamastack-service` (API port 8321). |
| `call-llama-with-github.sh` | End-to-end GitHub MCP chat demo (wrapper for `scripts/call_llama_with_github.py`). |
| `call-llama-with-kubernetes.sh` | End-to-end Kubernetes/OpenShift MCP chat demo (wrapper for `scripts/call_llama_with_kubernetes.py`). |
| `scripts/call_llama_with_github.py` | Multi-turn `/v1/chat/completions` + in-cluster GitHub MCP `tools/call` via `oc exec`. |
| `scripts/call_llama_with_kubernetes.py` | Multi-turn `/v1/chat/completions` + in-cluster Kubernetes MCP `tools/call` via `oc exec` (`/mcp` streamable HTTP). |
| `chat-payload-github-subset.json` | Sample chat payload: `vllm/MiniMax-M2.7`, inline GitHub tool schemas, user prompt. |
| `chat-payload-openshift-tekton-subset.json` | Sample chat payload: inline OpenShift/Kubernetes tool schemas (Tekton `PipelineRun` prompt). |
| `scripts/build_openshift_chat_payload.py` | Rebuild `chat-payload-openshift-tekton-subset.json` from a connector tools export. |
| `llama-stack-preparation.sh` | One-liner helper to register MCP tool groups with `llama-stack-client`. |
| `.gitignore` | Ignores local `_ref_*/` scratch directories. |

## Configure before deploy

1. **`openshift/secret.yaml`**  
   Set `stringData.vllm-api-token` if vLLM requires a real bearer token. Otherwise the default `fake` is often enough. Prefer not committing secrets: create the Secret with `oc create secret generic llamastack-credentials --from-literal=vllm-api-token='…' -n agentic-demo` and omit `secret.yaml` from `kustomization.yaml` if you manage the Secret out of band.

2. **`openshift/github-mcp-secret.yaml`**  
   Set `stringData.GITHUB_PERSONAL_ACCESS_TOKEN` to a [GitHub PAT](https://github.com/settings/personal-access-tokens/new) with the scopes your toolsets need. The [GitHub MCP Server](https://github.com/github/github-mcp-server) documents classic vs fine-grained tokens and scope filtering.  
   **Why a Secret:** the container image’s **HTTP** mode expects `Authorization: Bearer …` on each MCP request (unlike **stdio** mode, which uses the `GITHUB_PERSONAL_ACCESS_TOKEN` environment variable inside a single local process). Llama Stack’s connector config only stores a URL, not a GitHub token, so this repo uses an **nginx sidecar** that adds the `Authorization` header using the value from Secret `github-mcp-pat`. Llama Stack calls `http://github-mcp…:8080/` with no GitHub credentials; only workloads that can reach that `Service` can trigger GitHub API usage as that PAT—treat it as sensitive and use `NetworkPolicy` if required.

3. **`openshift/configmap-mcp-endpoints.yaml`**  
   Set **`VLLM_URL`** to your vLLM OpenAI base (cluster DNS, include **`/v1`**). The default `http://vllm-serving.agentic-demo.svc.cluster.local:8000/v1` is an in-cluster example—point at your real vLLM Service or Route. Defaults: **`MCP_GITHUB_SSE_URL`** → bundled **`github-mcp`** (streamable HTTP at **`/`**); **`MCP_OPENSHIFT_SSE_URL`** → bundled **`kubernetes-mcp`** (SSE at **`/sse`** for Llama Stack connectors). Point either URL elsewhere if you use an external MCP server. Edit **`openshift/kubernetes-mcp.yaml`** `Role` rules if MCP tools need writes, cluster-scoped access, or additional API groups.

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

**API Route** (Llama Stack HTTP/OpenAI-compatible):

```bash
oc get route llamastack -n agentic-demo -o jsonpath='{.spec.host}{"\n"}'
```

The Llama Stack HTTP API listens on port **8321** inside the cluster. OpenAI-compatible clients typically use `https://<route-host>/v1` (see [OpenAI compatibility](https://llamastack.github.io/docs/providers/openai)).

**Model names:** Use the stack id **`vllm/<vLLM-model-id>`** in chat and in `GET /v1/models` through Llama Stack—for example **`vllm/MiniMax-M2.7`** only if vLLM’s **`/v1/models`** entry `id` is exactly `MiniMax-M2.7` (common when you set **`--served-model-name`**). Bare `MiniMax-M2.7` is rejected. Discover the real id from vLLM (from any pod in the namespace): `curl -sS "http://<vllm-host>:<port>/v1/models"`. This overlay omits **`registered_resources.models`** in config so the stack auto-discovers models from **`VLLM_URL`** when you change the served model.

**Quick MCP + LLM check:** After deploy, run **`./call-llama-with-github.sh`** or **`./call-llama-with-kubernetes.sh`** (see **§3b**).

### MCP tool groups (why the model “sees no tools”)

`connectors` in `config.yaml` only register URLs for the **Connectors** API (`/v1beta/connectors/...` on server **0.7.x**). That is **not** the same as registering **tool groups** for **`GET /v1/tools`**. The provider `remote::model-context-protocol` does not auto-register a tool group, so **`GET /v1/tools`** stays empty until you register MCP endpoints as tool groups. Plain **`/v1/chat/completions`** also does not pull connector tools into the request automatically—the client must supply a **`tools`** array (inline in the payload, from **`GET /v1/tools`**, or via an **agents** flow). On **0.7.x**, the fastest way to verify MCP + LLM tool calling is **`call-llama-with-github.sh`** / **`call-llama-with-kubernetes.sh`** (see **§3b**).

**1. Verify connectors (optional)** — confirms Llama Stack can reach each MCP URL:

```bash
HOST=$(oc get route llamastack -n agentic-demo -o jsonpath='{.spec.host}')
curl -sS "https://${HOST}/v1beta/connectors" -H "Authorization: Bearer none"
curl -sS "https://${HOST}/v1beta/connectors/github/tools" -H "Authorization: Bearer none"
curl -sS "https://${HOST}/v1beta/connectors/openshift/tools" -H "Authorization: Bearer none"
```

**2. Register MCP tool groups** — same URLs as in `llamastack-mcp-endpoints`, **`--provider-id`** must match **`providers.tool_runtime[].provider_id`** in `config.yaml` (this repo uses **`model-context-protocol`**):

```bash
# Install: pip install "llama-stack-client>=0.7.0"
export LLAMA_STACK_BASE_URL="https://${HOST}"
llama-stack-client toolgroups register mcp-github --provider-id model-context-protocol --mcp-endpoint "http://github-mcp:8080/"
llama-stack-client toolgroups register mcp-openshift --provider-id model-context-protocol --mcp-endpoint "http://kubernetes-mcp:8080/sse"
```

**Self-signed TLS and `llama-stack-client`:** The CLI does **not** expose a “skip TLS verify” flag. It always uses the default HTTPS certificate validation when `LLAMA_STACK_BASE_URL` or `--endpoint` is `https://…`.

- **Easiest:** Port-forward the in-cluster **HTTP** Service (no Route TLS on the path from your machine to `127.0.0.1`):

  ```bash
  # Syntax: localPort:servicePort — use a number or the Service's port *name* (operator uses name "http", not "llama-stack-client").
  oc port-forward -n agentic-demo svc/llamastack-service 8321:http
  llama-stack-client --endpoint http://127.0.0.1:8321 toolgroups register mcp-github \
    --provider-id model-context-protocol --mcp-endpoint "http://github-mcp:8080/"
  llama-stack-client --endpoint http://127.0.0.1:8321 toolgroups register mcp-openshift \
    --provider-id model-context-protocol --mcp-endpoint "http://kubernetes-mcp:8080/sse"
  ```

- **`curl` against the Route:** add **`-k`** (insecure) or **`--cacert /path/to/cluster-ca.pem`** if you export the ingress/router CA.

- **Python (trust nothing / dev only):** [`LlamaStackClient`](https://github.com/meta-llama/llama-stack-client-python) accepts a custom **`httpx.Client`**; use that to disable verification (or point **`verify=`** at your cluster CA file—prefer that over `verify=False` long term):

  ```python
  import httpx
  from llama_stack_client import LlamaStackClient
  from llama_stack_client.types import toolgroup_register_params

  client = LlamaStackClient(
      base_url="https://your-route.apps.example.com",
      http_client=httpx.Client(verify=False),  # or verify="/path/to/cluster-ca.pem"
  )
  client.toolgroups.register(
      provider_id="model-context-protocol",
      toolgroup_id="mcp-github",
      mcp_endpoint=toolgroup_register_params.McpEndpoint(uri="http://github-mcp:8080/"),
  )
  ```

The **`--mcp-endpoint`** value is stored and called **from the Llama Stack pod**, so it must resolve inside the cluster (same as `MCP_*` URLs in `llamastack-mcp-endpoints`—short names like `http://github-mcp:8080/` work when Llama Stack runs in **`agentic-demo`**). Tool group ids (`mcp-github`, `mcp-openshift`) are arbitrary but must be unique.

**3. Verify tools are visible:**

Query parameter name is **`toolgroup_id`** (matches `ListToolsRequest` in the server—**not** `tool_group_id`).

```bash
curl -sS "https://${HOST}/v1/tools" -H "Authorization: Bearer none"
curl -sS "https://${HOST}/v1/tools?toolgroup_id=mcp-github" -H "Authorization: Bearer none"
curl -sS "https://${HOST}/v1/tools?toolgroup_id=mcp-openshift" -H "Authorization: Bearer none"
```

**`toolgroups list` vs `GET /v1/tools`:** The CLI **`toolgroups list`** (or **`GET /v1/toolgroups`**) only shows **registered tool groups** (id, provider, MCP URL)—it does **not** call GitHub MCP. **`GET /v1/tools`** triggers a **live MCP `list_tools`** from the **Llama Stack pod** to the endpoint you registered. An **empty `data` array** usually means that call failed or returned no tools (errors are often only in **server logs**, not in the JSON). Check **`oc logs`** on the llama-stack pod, **`NetworkPolicy`** egress to `github-mcp`, and from inside the pod: **`curl -sS http://github-mcp:8080/`** (or your MCP URL). A wrong **`toolgroup_id`** would normally yield **404** / tool group not found, not an empty list.

Registrations are stored on the Llama Stack PVC (`/.llama`); they survive pod restarts. Re-run **`toolgroups register`** if you change MCP URLs. You can also use **`llama-stack-preparation.sh`** (same commands as step 2) after setting **`LLAMA_STACK_BASE_URL`** or port-forwarding.

**3b. End-to-end chat with MCP tools (recommended on 0.7.x)**

RHOAI **Llama Stack 0.7.x** does **not** expose **`/v1/tool-runtime/list-tools`** or **`/v1/tool-runtime/invoke`** over HTTP (those routes return **404**). To exercise the full model → tool → MCP → model loop, use the bundled scripts. They:

1. POST **`/v1/chat/completions`** with a **`tools`** array inlined in the payload (see **`chat-payload-*.json`**).
2. When the model returns **`tool_calls`**, invoke each tool from inside the **`llamastack`** pod via **`oc exec`** → MCP **`tools/call`** (GitHub: streamable HTTP at **`http://github-mcp:8080/`**; Kubernetes: streamable HTTP at **`http://kubernetes-mcp:8080/mcp`**).
3. POST chat again with **`role: tool`** messages until the model returns a final answer (up to **`MAX_CHAT_TURNS`**, default **10**).

**Requirements:** `oc` logged in to the cluster, **`python3`** on your laptop, network access to the Llama Stack Route (scripts skip TLS verify by default).

```bash
# GitHub: list repos for a user (username is the first argument)
export LLAMA_STACK_BASE_URL="https://$(oc get route llamastack -n agentic-demo -o jsonpath='{.spec.host}')"
./call-llama-with-github.sh octocat

# OpenShift/Kubernetes: e.g. find failed Tekton PipelineRuns in agentic-demo
./call-llama-with-kubernetes.sh
```

Optional environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLAMA_STACK_BASE_URL` | Hardcoded example Route in script | Override with your Route host (see example below) or `http://127.0.0.1:8321` with port-forward |
| `LLAMA_STACK_INSECURE` | `1` | Set to `0` to verify TLS certificates |
| `CHAT_PAYLOAD` | `chat-payload-*.json` | Path to request JSON |
| `OPENSHIFT_NAMESPACE` | `agentic-demo` | Namespace for `oc exec` |
| `LLAMASTACK_DEPLOY` | `llamastack` | Deployment name for `oc exec` |
| `GITHUB_MCP_URL` | `http://github-mcp:8080/` | In-cluster GitHub MCP URL |
| `KUBERNETES_MCP_URL` | `http://kubernetes-mcp:8080/mcp` | In-cluster Kubernetes MCP URL (streamable HTTP) |
| `MAX_CHAT_TURNS` | `10` | Max chat ↔ tool round-trips |

Progress and tool invocations are printed on **stderr**; JSON chat responses on **stdout**.

**If `GET /v1/tools?toolgroup_id=…` returns `{"data":[]}`:** The HTTP call succeeded but **MCP `list_tools` did not return tools** (failures are often only in **pod logs**, not the JSON body). Common causes:

1. **URL mismatch vs connectors** — Re-register the tool group using the **exact** MCP URL from `llamastack-mcp-endpoints` (including a **trailing slash** if present), e.g. **`http://github-mcp:8080/`** not `http://github-mcp:8080`. Streamable HTTP can be sensitive to that. Then retry **`GET /v1/tools?toolgroup_id=mcp-github`**.
2. **A/B test the connector path** (same URL as `config.yaml` connectors): **`GET /v1beta/connectors/github/tools`** — if this is non-empty but tool-group listing stays empty, the stored **`mcp_endpoint`** on the tool group likely differs from the connector URL.
3. **Network from the Llama Stack pod:** `oc exec -n agentic-demo deploy/llamastack -- curl -sS -o /dev/null -w "%{http_code}" http://github-mcp:8080/`
4. **Logs while repeating the request:** `oc logs -n agentic-demo -l app=llama-stack --tail=200` and look for MCP / `list_tools` / connection errors.

**4. Agent flows:** If you use features that rely on the **Agents** API, add **`agents`** under **`apis`** in `openshift/config/config.yaml` and redeploy (per [Llama Stack docs](https://llamastack.github.io/docs/) for your distribution version).

## OpenShift notes

- **Kubernetes MCP image:** `quay.io/mcp-servers/kubernetes-mcp-server` must be pullable from your cluster (mirror or pull secrets if needed). The pod uses the **`kubernetes-mcp`** `ServiceAccount` for API access; no kubeconfig Secret is required for the default layout. The image supports **SSE** (`/sse`, used for Llama Stack connector/tool-group URLs) and **streamable HTTP** (`/mcp`, used by **`call-llama-with-kubernetes.sh`**).
- **Image pulls:** This overlay uses **`registry.redhat.io/rhoai/odh-llama-stack-core-rhel9:v3.4`** (RHOAI 3.4 / Llama Stack 0.7.x). The cluster global pull secret must include `registry.redhat.io`. Upstream **`docker.io/llamastack/distribution-starter`** may require separate Docker Hub credentials if you switch back to that image.
- **Security context / SCC:** If the pod fails to start with permission errors, work with your cluster admin on the appropriate SCC and ServiceAccount (the operator creates a per-CR ServiceAccount by default).
- **GitHub MCP nginx sidecar:** Uses `nginxinc/nginx-unprivileged` plus `emptyDir` mounts and `pod.spec.securityContext.fsGroup` set to **`1001040000`**, matching the **`agentic-demo`** namespace UID annotation `1001040000/10000` (first number = usable `fsGroup` / group for volume permissions). If your namespace uses a different range, run `oc get namespace agentic-demo -o jsonpath='{.metadata.annotations.openshift\.io/sa\.scc\.uid-range}{"\n"}'` and set `fsGroup` in `github-mcp.yaml` to that range’s base (or a value allowed by `openshift.io/sa.scc.supplemental-groups`). If `docker.io/nginxinc/nginx-unprivileged` is blocked, mirror it or swap the image.
- **TLS:** The sample Route uses **edge** termination. For re-encrypt or passthrough, change `openshift/route.yaml` accordingly.
- **Config updates:** Changing `openshift/config/config.yaml` and re-applying updates the generated ConfigMap; the operator’s ConfigMap hash annotation should roll the Deployment. If not, delete the pod to force a restart.

## Troubleshooting

| Symptom | Things to check |
|--------|------------------|
| `Distribution name not supported` (e.g. for `starter`) | The RHOAI operator only accepts certain `spec.server.distribution.name` values. This repo uses **`distribution.image`** (`registry.redhat.io/rhoai/odh-llama-stack-core-rhel9:v3.4`) so reconciliation does not depend on that list. Upgrade RHOAI if you need newer embedded distribution names. |
| CR not reconciling / no pods | RHOAI Llama Stack operator **Managed** in `DataScienceCluster`; operator pod running in **`redhat-ods-applications`**; `oc describe llamastackdistribution llamastack -n agentic-demo`. |
| LLM / chat “no tools” | **`connectors` ≠ tool groups.** Register MCP URLs with `llama-stack-client toolgroups register … --provider-id model-context-protocol --mcp-endpoint <url>` (see **MCP tool groups** above), or pass **`tools`** inline in **`/v1/chat/completions`** as in **`chat-payload-*.json`**. Confirm connector reachability with **`GET /v1beta/connectors/{id}/tools`**. For a full tool loop on **0.7.x**, use **`call-llama-with-github.sh`** / **`call-llama-with-kubernetes.sh`**. |
| MCP tools missing or errors | MCP pods running; URLs in `llamastack-mcp-endpoints` correct; network policies allow egress from Llama Stack to MCP Services; GitHub MCP needs nginx + PAT sidecar as in `github-mcp.yaml`. Kubernetes MCP RBAC is namespace-scoped—cluster-wide tools (e.g. **`namespaces_list`**) return forbidden unless you widen the `Role`. |
| **`GET /v1/tools?toolgroup_id=…` returns `[]`** | Parameter **`toolgroup_id`** is correct. Empty **`data`** means MCP listing from the **Llama Stack pod** failed or returned no tools—see **§3** above and pod logs. **`toolgroups list`** only confirms registration, not MCP reachability. Inline **`tools`** in chat payloads work without tool-group registration. |
| **`/v1/tool-runtime/...` → Not Found** | On **Llama Stack 0.7.x** (RHOAI `odh-llama-stack-core-rhel9:v3.4`), **`/v1/tool-runtime/list-tools`** and **`/v1/tool-runtime/invoke`** are not served over HTTP. Use **`call-llama-with-github.sh`** / **`call-llama-with-kubernetes.sh`**, or invoke MCP **`tools/call`** from a pod that can reach the MCP Service. |
| **`GET /v1alpha/connectors/...` → Not Found** | On **llama-stack 0.7.x**, connector routes live under **`/v1beta/connectors`** (0.7.1+ may also expose **`/v1/connectors`**). Use **`/v1beta/...`** or **`/v1/...`** instead of **`/v1alpha/...`**. |
| **`curl` from Llama Stack pod → GitHub MCP “Authorization header is badly formatted”** | Hit the **Service port 8080** (nginx); it injects **`Authorization: Bearer <PAT>`** to the MCP container. **Do not** send a broken client `Authorization` header unless you know nginx still overwrites it. Prefer: **`curl -sS http://github-mcp.agentic-demo.svc:8080/`** with **no** `Authorization` header. If you curl **8082** (MCP only, not exposed by the Service), you must send a valid **`Authorization: Bearer <ghp_…>`** yourself. **Empty or whitespace PAT** in **`github-mcp-pat`** yields **`Bearer `** upstream and the same error—fix the Secret. |
| **`GET /v1beta/connectors/github` → 500**; nginx logs **`POST /` 400** then **`GET /` 400** (`python-httpx`) | **`GET /v1beta/connectors`** only lists stored connector ids (no MCP call). **`GET …/connectors/{id}`** calls MCP **`initialize`** (**POST /**) and the streamable follow-up (**GET /**)—that matches the nginx access log; **400 is from github-mcp-server**, not nginx generating it. Common causes: (1) **PAT Secret** — value must be a **raw** GitHub token (`ghp_…`, `github_pat_…`, …), **not** prefixed with `Bearer `, not empty; otherwise [ParseAuthorizationHeader](https://github.com/github/github-mcp-server/blob/main/pkg/utils/token.go) returns **400**. (2) **Stray `X-MCP-Tools` / `X-MCP-Toolsets`** headers on the request—invalid tool names produce **400** *unknown tools specified in WithTools*. The sample **`github-mcp.yaml`** clears those headers at nginx. Confirm the response body with a repro from a debug pod: **`curl -sv -X POST http://github-mcp:8080/ …`** or check **github-mcp-server** container stderr. HTTP path is **`/v1beta/connectors`** on 0.7.x (OpenAPI prefix `v1beta`), not Kubernetes-style `v1alpha1`. |
| Same flow but nginx shows **`403`** for **`POST /`** and **`GET /`** | Often **[go-sdk DNS rebinding protection](https://github.com/modelcontextprotocol/go-sdk/blob/main/mcp/streamable.go)**: the MCP server listens on **127.0.0.1** (nginx `proxy_pass` from the sidecar) but **`Host`** was the cluster name (**`github-mcp`**, …), so the handler returns **403** *Forbidden: invalid Host header*. **`github-mcp.yaml`** sets **`proxy_set_header Host 127.0.0.1`** toward **8082** and **`X-Forwarded-Host`** to the original name. If you still see **403**, check the response body: **cross-origin / Origin** checks can also forbid; you can set **`MCPGODEBUG=disablecrossoriginprotection=1`** on the **github-mcp-server** container (see go-sdk `mcpgodebug`) as a temporary workaround, or **`MCPGODEBUG=disablelocalhostprotection=1`** if you cannot change nginx. |
| `llama-stack-client` SSL / certificate errors | CLI has no `--insecure`. Use **`oc port-forward`** to **`http://127.0.0.1:8321`**, or a **Python** `LlamaStackClient(..., http_client=httpx.Client(verify=False))` / **`verify="/path/to/ca.pem"`**, or fix **`curl`** with **`-k`** or **`--cacert`**. |
| Client / server version mismatch (e.g. client 0.6.x, server 0.7.x) | Upgrade the library from PyPI: **`python3 -m pip install -U "llama-stack-client>=0.7.0"`** (package name uses a **hyphen**). Current releases expect **Python 3.12+**. Confirm with **`python3 -c "import llama_stack_client; print(llama_stack_client.__version__)"`**. |
| Model not found / vLLM errors | `VLLM_URL` must be reachable from the Llama Stack pod (in-cluster Service URL, not only an external Route). Chat `model` must be **`vllm/<id>`** matching vLLM’s `/v1/models`. Check logs; set `VLLM_TLS_VERIFY=false` on the Deployment if vLLM uses HTTPS with an untrusted CA. |
| SQLite / disk errors | PVC bound; `SQLITE_STORE_DIR` matches writable path under `/.llama` (set in the CR). |
| `github-mcp` nginx: conf.d not writable / `client_temp` permission denied | OpenShift random UID vs read-only root; ensure you applied the `emptyDir` + `fsGroup` + `nginxinc/nginx-unprivileged` manifest. Adjust `fsGroup` if your SCC restricts it. |

## References

- [Working with Llama Stack (RHOAI 3.4)](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html-single/working_with_llama_stack/)
- [Installing OpenShift AI Self-Managed](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html-single/installing_and_uninstalling_openshift_ai_self-managed/index)
- [Llama Stack configuration / distributions](https://llamastack.github.io/docs/)
