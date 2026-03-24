"""One-off helper: rebuild chat-payload-openshift-tekton-subset.json from openshift-tools export."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = Path.home() / "Downloads" / "openshift-tools.json"


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    data = json.loads(src.read_text(encoding="utf-8"))
    by = {t["name"]: t for t in data["data"]}

    selected = [
        "namespaces_list",
        "resources_list",
        "resources_get",
        "events_list",
        "pods_list",
        "pods_list_in_namespace",
        "pods_log",
    ]

    extras = {
        "resources_list": (
            " For Tekton: use apiVersion tekton.dev/v1 (or tekton.dev/v1beta1 on older OpenShift Pipelines), "
            "kind PipelineRun. Omit namespace to list across all namespaces (if RBAC allows). "
            "Use labelSelector when known (e.g. tekton.dev/pipeline). "
            "Inspect status.conditions for type Succeeded status False for failures."
        ),
        "resources_get": (
            " For Git repo correlation: PipelineRun metadata.annotations often include Pipelines-as-Code keys "
            "(pipelinesascode.tekton.dev/url, repository, git-url, sha) or spec.params may hold repo/URL. "
            "If unclear, fetch Pipeline (spec.pipelineRef) or TaskRuns in the same namespace."
        ),
        "pods_log": (
            " For Tekton Task pod container logs; set namespace from the PipelineRun. "
            "Use previous=true for terminated container logs. Increase tail for more lines."
        ),
        "pods_list": (
            " With labelSelector tekton.dev/pipelineRun=<pipelinerun-name> to find Task pods for a run, then pods_log."
        ),
    }

    def to_openai(t: dict) -> dict:
        base = t.get("description") or ""
        extra = extras.get(t["name"], "")
        return {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": (base + extra).strip(),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        }

    payload = {
        "model": "vllm/MiniMax-M2.5",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Find Tekton PipelineRuns that have failed in the cluster. "
                    "For each failure, determine the associated Git repository URL when present "
                    "(annotations, params, or related Pipeline spec). "
                    "Then retrieve logs from the relevant failed Pods. "
                    "If API access is namespace-scoped (typical for the bundled kubernetes-mcp Role), "
                    "limit listing to namespaces you can read (e.g. agentic-demo)."
                ),
            }
        ],
        "tool_choice": "auto",
        "tools": [to_openai(by[n]) for n in selected],
    }

    out = ROOT / "chat-payload-openshift-tekton-subset.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
