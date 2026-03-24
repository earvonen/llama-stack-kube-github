# Llama Stack on OpenShift (vLLM + MCP)

All resources in this overlay use the OpenShift/Kubernetes namespace **`agentic-demo`**.

Kubernetes/OpenShift manifests to run [Llama Stack](https://llamastack.github.io/) with:

- **Inference:** [vLLM](https://github.com/vllm-project/vllm) on the cluster (`remote::vllm`, provider id **`vllm`**), OpenAI-compatible **`/v1`**. The sample config assumes you serve **MiniMax-family** (or other) weights from that vLLM instance—not the MiniMax cloud API.
- **Tools:** MCP connectors for **GitHub** and **OpenShift**. This repo includes an optional in-cluster **GitHub MCP** Deployment (official `ghcr.io/github/github-mcp-server` in HTTP mode plus an nginx sidecar that injects a PAT from a **Secret**). You still supply your **OpenShift / Kubernetes MCP** endpoint separately in `configmap-mcp-endpoints.yaml`.

The [Llama Stack Kubernetes Operator](https://github.com/llamastack/llama-stack-k8s-operator) reconciles a `LlamaStackDistribution` custom resource into a Deployment, Service, PVC, and related objects. This repository adds a Kustomize overlay, stack `config.yaml`, non-secret endpoint tuning, OpenShift **Routes** for the API and for the **[Llama Stack UI](https://llamastack.github.io/docs/distributions/llama_stack_ui)** playground (`docker.io/llamastack/ui`).

## Prerequisites

1. **OpenShift cluster** with `oc` configured and permission to install operators or apply CRDs in your target namespace scope (cluster admins typically install the operator once per cluster).
2. **Llama Stack operator** installed, for example:

   ```bash
   oc apply -f https://github.com/llamastack/llama-stack-k8s-operator/releases/latest/download/operator.yaml
   ```

   Confirm the `LlamaStackDistribution` CRD exists: `oc get crd llamastackdistributions.llamastack.io`.

3. **vLLM** reachable from namespace **`agentic-demo`** (Service URL + port; OpenAI base URL must end with **`/v1`**). Optionally a bearer token if your vLLM is protected.

4. **GitHub PAT** if you use the bundled GitHub MCP manifests: create or edit Secret `github-mcp-pat` (see below).

5. **Kubernetes / OpenShift MCP** — `openshift/kubernetes-mcp.yaml` deploys **`quay.io/mcp-servers/kubernetes-mcp-server`** with a dedicated **`ServiceAccount`** and a namespace-scoped **read-only** `Role` (`get`, `list`, `watch`). If MCP tools need **create/update/delete** or **cluster-scoped** reads (`Node`, etc.), edit that `Role` (or switch to a `ClusterRole` + `ClusterRoleBinding` with care). Ensure `MCP_OPENSHIFT_SSE_URL` in `configmap-mcp-endpoints.yaml` matches the server’s transport (**`/sse`** for this image).

## Repository layout

| Path | Purpose |
|------|---------|
| `openshift/kustomization.yaml` | Kustomize entrypoint: namespace, ConfigMaps, Secret, CR, Route; builds `llamastack-server-config` from `config/config.yaml`. |
| `openshift/config/config.yaml` | Llama Stack stack config (mounted as `/etc/llama-stack/config.yaml` in the pod). |
| `openshift/github-mcp-secret.yaml` | GitHub PAT for the in-cluster GitHub MCP proxy (`GITHUB_PERSONAL_ACCESS_TOKEN`). |
| `openshift/github-mcp.yaml` | `Deployment` (github-mcp-server `http` + nginx injecting `Authorization`), `Service` `github-mcp:8080`, nginx `ConfigMap`. |
| `openshift/kubernetes-mcp.yaml` | `Deployment` + `Service` **`kubernetes-mcp:8080`**, `ServiceAccount`, namespace **`Role`/`RoleBinding`** (read-only MCP defaults). SSE MCP URL path **`/sse`**. |
| `openshift/configmap-mcp-endpoints.yaml` | Non-secret values: `MCP_*` connector base URLs, **`VLLM_URL`** (vLLM OpenAI base, e.g. `http://my-vllm:8000/v1`). |
| `openshift/secret.yaml` | Optional vLLM bearer token key **`vllm-api-token`** (many in-cluster servers accept `fake`). |
| `openshift/llamastackdistribution.yaml` | `LlamaStackDistribution` CR (`starter` image, PVC under `/.llama`, env wiring). |
| `openshift/route.yaml` | Edge TLS `Route` to Service `llamastack-service` (API port 8321). |
| `openshift/llama-stack-ui.yaml` | [Llama Stack UI](https://llamastack.github.io/docs/distributions/llama_stack_ui) playground: `Deployment` + `Service` `llamastack-ui` (`LLAMA_STACK_BACKEND_URL` → `http://llamastack-service:8321`). |
| `openshift/route-ui.yaml` | Edge TLS `Route` to the UI Service (port 8322). |
| `.gitignore` | Ignores local `_ref_*/` scratch directories. |

## Configure before deploy

1. **`openshift/secret.yaml`**  
   Set `stringData.vllm-api-token` if vLLM requires a real bearer token. Otherwise the default `fake` is often enough. Prefer not committing secrets: create the Secret with `oc create secret generic llamastack-credentials --from-literal=vllm-api-token='…' -n agentic-demo` and omit `secret.yaml` from `kustomization.yaml` if you manage the Secret out of band.

2. **`openshift/github-mcp-secret.yaml`**  
   Set `stringData.GITHUB_PERSONAL_ACCESS_TOKEN` to a [GitHub PAT](https://github.com/settings/personal-access-tokens/new) with the scopes your toolsets need. The [GitHub MCP Server](https://github.com/github/github-mcp-server) documents classic vs fine-grained tokens and scope filtering.  
   **Why a Secret:** the container image’s **HTTP** mode expects `Authorization: Bearer …` on each MCP request (unlike **stdio** mode, which uses the `GITHUB_PERSONAL_ACCESS_TOKEN` environment variable inside a single local process). Llama Stack’s connector config only stores a URL, not a GitHub token, so this repo uses an **nginx sidecar** that adds the `Authorization` header using the value from Secret `github-mcp-pat`. Llama Stack calls `http://github-mcp…:8080/` with no GitHub credentials; only workloads that can reach that `Service` can trigger GitHub API usage as that PAT—treat it as sensitive and use `NetworkPolicy` if required.

3. **`openshift/configmap-mcp-endpoints.yaml`**  
   Set **`VLLM_URL`** to your vLLM OpenAI base (cluster DNS, include **`/v1`**). Defaults: **`MCP_GITHUB_SSE_URL`** → bundled **`github-mcp`** (streamable HTTP at **`/`**); **`MCP_OPENSHIFT_SSE_URL`** → bundled **`kubernetes-mcp`** (SSE at **`/sse`**). Point either URL elsewhere if you use an external MCP server. Edit **`openshift/kubernetes-mcp.yaml`** `Role` rules if MCP tools need writes or cluster-scoped access.

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

**Playground (Llama Stack UI)** — open `https://<host>/` from:

```bash
oc get route llamastack-ui -n agentic-demo -o jsonpath='{.spec.host}{"\n"}'
```

The UI pod talks to the API **inside the cluster** (`http://llamastack-service:8321`), so you do not need browser CORS changes for that path.

### NextAuth URL (after the UI Route exists)

If you enable **GitHub OAuth** in the UI (`GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`), set `NEXTAUTH_URL` to the **public HTTPS URL** of the UI Route (see [Llama Stack UI env docs](https://llamastack.github.io/docs/distributions/llama_stack_ui)):

```bash
HOST=$(oc get route llamastack-ui -n agentic-demo -o jsonpath='{.spec.host}')
oc set env deployment/llamastack-ui -n agentic-demo NEXTAUTH_URL=https://$HOST
```

The Llama Stack HTTP API listens on port **8321** inside the cluster. OpenAI-compatible clients typically use `https://<route-host>/v1` (see [OpenAI compatibility](https://llamastack.github.io/docs/providers/openai)).

**Model names:** Use the stack id **`vllm/<vLLM-model-id>`** in chat and in `GET /v1/models` through Llama Stack—for example **`vllm/MiniMax-M2.5`** only if vLLM’s **`/v1/models`** entry `id` is exactly `MiniMax-M2.5` (common when you set **`--served-model-name`**). Bare `MiniMax-M2.5` is rejected. Discover the real id from vLLM (from any pod in the namespace): `curl -sS "http://<vllm-host>:<port>/v1/models"`. If the id differs (e.g. a Hugging Face repo id), either edit **`registered_resources.models`** in `openshift/config/config.yaml` (`model_id` / optional `provider_model_id`) or rely on registry refresh after vLLM is reachable at startup.

### MCP tool groups (why the model “sees no tools”)

`connectors` in `config.yaml` only register URLs for the **Connectors** API (`/v1alpha/connectors/...` on server **0.6.x**—not `v1beta`). That is **not** the same as registering **tool groups** for the **tool runtime**. The provider `remote::model-context-protocol` does not auto-register a tool group, so **`GET /v1/tools`** stays empty until you register MCP endpoints as tool groups. Plain **`/v1/chat/completions`** also does not pull connector tools into the request; the client (or an **agents** flow) must supply tool definitions, often after listing them from the stack.

**1. Verify connectors (optional)** — confirms Llama Stack can reach each MCP URL:

```bash
HOST=$(oc get route llamastack -n agentic-demo -o jsonpath='{.spec.host}')
curl -sS "https://${HOST}/v1alpha/connectors" -H "Authorization: Bearer none"
curl -sS "https://${HOST}/v1alpha/connectors/github/tools" -H "Authorization: Bearer none"
curl -sS "https://${HOST}/v1alpha/connectors/openshift/tools" -H "Authorization: Bearer none"
```

**2. Register MCP tool groups** — same URLs as in `llamastack-mcp-endpoints`, **`--provider-id`** must match **`providers.tool_runtime[].provider_id`** in `config.yaml` (this repo uses **`model-context-protocol`**):

```bash
# Install: pip install llama-stack-client
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

Registrations are stored on the Llama Stack PVC (`/.llama`); they survive pod restarts. Re-run **`toolgroups register`** if you change MCP URLs.

**3b. Confirm Llama Stack can drive GitHub MCP (curl, no LLM required)** — the **tool-runtime** API lists and invokes tools using the same routing as agents. Query param is **`tool_group_id`** (underscore), not `toolgroup_id`:

```bash
BASE="http://127.0.0.1:8321"   # or https://your-route — add -k if needed
AUTH="Authorization: Bearer none"

# List tool names + schemas (from the Llama Stack pod → MCP, same as UI/client)
curl -sS "${BASE}/v1/tool-runtime/list-tools?tool_group_id=mcp-github" -H "${AUTH}"

# Invoke one tool (replace tool_name and kwargs using the list output / input_schema)
curl -sS "${BASE}/v1/tool-runtime/invoke" -H "${AUTH}" -H "Content-Type: application/json" \
  -d '{"tool_name":"<name-from-list>","kwargs":{}}'
```

A successful **`invoke`** response (or a clear MCP/GitHub error from bad args) proves the stack reaches **`http://github-mcp:8080`** with your nginx-injected PAT. It does **not** by itself prove the **LLM** will choose tools—that needs **`/v1/chat/completions`** with a **`tools`** array built from **`GET /v1/tools`**, a model that supports tool calling, and a follow-up turn after **`tool_calls`** (often via **`POST /v1/tool-runtime/invoke`** with the parsed `name` / `arguments`).

**If `/v1/tool-runtime/list-tools` or `/v1/tools` returns `{"data":[]}`:** The HTTP call succeeded but **MCP `list_tools` did not return tools** (failures are often only in **pod logs**, not the JSON body). Common causes:

1. **URL mismatch vs connectors** — Re-register the tool group using the **exact** MCP URL from `llamastack-mcp-endpoints` (including a **trailing slash** if present), e.g. **`http://github-mcp:8080/`** not `http://github-mcp:8080`. Streamable HTTP can be sensitive to that. Then retry **`GET /v1/tools?toolgroup_id=mcp-github`** and **`GET /v1/tool-runtime/list-tools?tool_group_id=mcp-github`**.
2. **A/B test the connector path** (same URL as `config.yaml` connectors): **`GET /v1alpha/connectors/github/tools`** — if this is non-empty but tool-group listing stays empty, the stored **`mcp_endpoint`** on the tool group likely differs from the connector URL.
3. **Network from the Llama Stack pod:** `oc exec -n agentic-demo deploy/<llama-stack-deployment> -- curl -sS -o /dev/null -w "%{http_code}" http://github-mcp:8080/`
4. **Logs while repeating the request:** `oc logs -n agentic-demo -l app=llama-stack --tail=200` and look for MCP / `list_tools` / connection errors.

**4. Agent / UI flows:** If you use features that rely on the **Agents** API, add **`agents`** under **`apis`** in `openshift/config/config.yaml` and redeploy (per [Llama Stack docs](https://llamastack.github.io/docs/) for your distribution version).

## OpenShift notes

- **Kubernetes MCP image:** `quay.io/mcp-servers/kubernetes-mcp-server` must be pullable from your cluster (mirror or pull secrets if needed). The pod uses the **`kubernetes-mcp`** `ServiceAccount` for API access; no kubeconfig Secret is required for the default layout.
- **Image pulls:** If your cluster cannot pull `docker.io/llamastack/distribution-starter`, mirror the image or add pull secrets and adjust the operator or distribution image settings per your org’s policy.
- **Security context / SCC:** If the pod fails to start with permission errors, work with your cluster admin on the appropriate SCC and ServiceAccount (the operator creates a per-CR ServiceAccount by default).
- **GitHub MCP nginx sidecar:** Uses `nginxinc/nginx-unprivileged` plus `emptyDir` mounts and `pod.spec.securityContext.fsGroup` set to **`1000940000`**, matching the **`agentic-demo`** namespace UID annotation `1000940000/10000` (first number = usable `fsGroup` / group for volume permissions). If your namespace uses a different range, run `oc get namespace agentic-demo -o jsonpath='{.metadata.annotations.openshift\.io/sa\.scc\.uid-range}{"\n"}'` and set `fsGroup` in `github-mcp.yaml` to that range’s base (or a value allowed by `openshift.io/sa.scc.supplemental-groups`). If `docker.io/nginxinc/nginx-unprivileged` is blocked, mirror it or swap the image.
- **TLS:** The sample Route uses **edge** termination. For re-encrypt or passthrough, change `openshift/route.yaml` accordingly.
- **Config updates:** Changing `openshift/config/config.yaml` and re-applying updates the generated ConfigMap; the operator’s ConfigMap hash annotation should roll the Deployment. If not, delete the pod to force a restart.

## Troubleshooting

| Symptom | Things to check |
|--------|------------------|
| `Distribution name not supported` (e.g. for `starter`) | The operator only accepts `spec.server.distribution.name` values baked into its embedded `distributions.json`. Older or custom builds may omit `starter`. This repo uses **`distribution.image`** (`docker.io/llamastack/distribution-starter:latest`) so reconciliation does not depend on that list. Alternatively upgrade the [operator](https://github.com/llamastack/llama-stack-k8s-operator/releases) to a release whose embedded distributions include `starter`, then you may switch to `name: starter` and remove `image`. |
| CR not reconciling / no pods | Operator installed and watching your namespace; `oc describe llamastackdistribution llamastack -n agentic-demo`. |
| LLM / chat “no tools” | **`connectors` ≠ tool groups.** Register MCP URLs with `llama-stack-client toolgroups register … --provider-id model-context-protocol --mcp-endpoint <url>` (see **MCP tool groups** above). Confirm with **`GET /v1/tools`**. Chat completions need a **`tools`** payload unless an **agents** flow adds them. |
| MCP tools missing or errors | MCP pods running; URLs in `llamastack-mcp-endpoints` correct; network policies allow egress from Llama Stack to MCP Services; GitHub MCP needs nginx + PAT sidecar as in `github-mcp.yaml`. |
| **`GET /v1/tools?toolgroup_id=…` returns `[]`** | Parameter **`toolgroup_id`** is correct. Empty **`data`** means MCP listing from the **Llama Stack pod** failed or returned no tools—see **§3** above and pod logs. **`toolgroups list`** only confirms registration, not MCP reachability. |
| **`GET /v1/tool-runtime/list-tools?tool_group_id=…` returns `[]`** | Param **`tool_group_id`** is correct for this route (underscore). Same empty-list causes as **`/v1/tools`**; align **`mcp_endpoint`** with **`http://github-mcp:8080/`** (trailing slash) and compare **`/v1alpha/connectors/github/tools`**. |
| **`GET /v1beta/connectors/...` → Not Found** | On **llama-stack 0.6.x**, connector routes live under **`/v1alpha/connectors`** (see `llama_stack_api.connectors.fastapi_routes`). Use **`/v1alpha/...`** instead. |
| **`curl` from Llama Stack pod → GitHub MCP “Authorization header is badly formatted”** | Hit the **Service port 8080** (nginx); it injects **`Authorization: Bearer <PAT>`** to the MCP container. **Do not** send a broken client `Authorization` header unless you know nginx still overwrites it. Prefer: **`curl -sS http://github-mcp.agentic-demo.svc:8080/`** with **no** `Authorization` header. If you curl **8082** (MCP only, not exposed by the Service), you must send a valid **`Authorization: Bearer <ghp_…>`** yourself. **Empty or whitespace PAT** in **`github-mcp-pat`** yields **`Bearer `** upstream and the same error—fix the Secret. |
| **`GET /v1alpha/connectors/github` → 500**; nginx logs **`POST /` 400** then **`GET /` 400** (`python-httpx`) | **`GET /v1alpha/connectors`** only lists stored connector ids (no MCP call). **`GET …/connectors/{id}`** calls MCP **`initialize`** (**POST /**) and the streamable follow-up (**GET /**)—that matches the nginx access log; **400 is from github-mcp-server**, not nginx generating it. Common causes: (1) **PAT Secret** — value must be a **raw** GitHub token (`ghp_…`, `github_pat_…`, …), **not** prefixed with `Bearer `, not empty; otherwise [ParseAuthorizationHeader](https://github.com/github/github-mcp-server/blob/main/pkg/utils/token.go) returns **400**. (2) **Stray `X-MCP-Tools` / `X-MCP-Toolsets`** headers on the request—invalid tool names produce **400** *unknown tools specified in WithTools*. The sample **`github-mcp.yaml`** clears those headers at nginx. Confirm the response body with a repro from a debug pod: **`curl -sv -X POST http://github-mcp:8080/ …`** or check **github-mcp-server** container stderr. HTTP path is **`/v1alpha/connectors`** (OpenAPI prefix `v1alpha`), not Kubernetes-style `v1alpha1`. |
| Same flow but nginx shows **`403`** for **`POST /`** and **`GET /`** | Often **[go-sdk DNS rebinding protection](https://github.com/modelcontextprotocol/go-sdk/blob/main/mcp/streamable.go)**: the MCP server listens on **127.0.0.1** (nginx `proxy_pass` from the sidecar) but **`Host`** was the cluster name (**`github-mcp`**, …), so the handler returns **403** *Forbidden: invalid Host header*. **`github-mcp.yaml`** sets **`proxy_set_header Host 127.0.0.1`** toward **8082** and **`X-Forwarded-Host`** to the original name. If you still see **403**, check the response body: **cross-origin / Origin** checks can also forbid; you can set **`MCPGODEBUG=disablecrossoriginprotection=1`** on the **github-mcp-server** container (see go-sdk `mcpgodebug`) as a temporary workaround, or **`MCPGODEBUG=disablelocalhostprotection=1`** if you cannot change nginx. |
| `llama-stack-client` SSL / certificate errors | CLI has no `--insecure`. Use **`oc port-forward`** to **`http://127.0.0.1:8321`**, or a **Python** `LlamaStackClient(..., http_client=httpx.Client(verify=False))` / **`verify="/path/to/ca.pem"`**, or fix **`curl`** with **`-k`** or **`--cacert`**. |
| Client / server version mismatch (e.g. client 0.2.x, server 0.6.x) | Upgrade the library from PyPI: **`python3 -m pip install -U "llama-stack-client>=0.6.0"`** (package name uses a **hyphen**). Current releases expect **Python 3.12+**. Confirm with **`python3 -c "import llama_stack_client; print(llama_stack_client.__version__)"`**. |
| Model not found / vLLM errors | `VLLM_URL` must be reachable from the Llama Stack pod (in-cluster Service URL, not only an external Route). Chat `model` must be **`vllm/<id>`** matching vLLM’s `/v1/models`. Check logs; set `VLLM_TLS_VERIFY=false` on the Deployment if vLLM uses HTTPS with an untrusted CA. |
| SQLite / disk errors | PVC bound; `SQLITE_STORE_DIR` matches writable path under `/.llama` (set in the CR). |
| `github-mcp` nginx: conf.d not writable / `client_temp` permission denied | OpenShift random UID vs read-only root; ensure you applied the `emptyDir` + `fsGroup` + `nginxinc/nginx-unprivileged` manifest. Adjust `fsGroup` if your SCC restricts it. |

## References

- [Llama Stack Kubernetes Operator docs](https://llama-stack-k8s-operator.pages.dev/)
- [Llama Stack configuration / distributions](https://llamastack.github.io/docs/)
- [Llama Stack operator releases](https://github.com/llamastack/llama-stack-k8s-operator/releases)
