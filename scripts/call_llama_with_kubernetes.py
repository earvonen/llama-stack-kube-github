#!/usr/bin/env python3
"""Multi-turn chat against Llama Stack with inline Kubernetes/OpenShift tools.

Turn 1: POST /v1/chat/completions (tools in payload).
Turn 2: invoke each tool_call via in-cluster Kubernetes MCP (oc exec), then POST chat again.
"""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAYLOAD = ROOT / "chat-payload-openshift-tekton-subset.json"
DEFAULT_BASE_URL = "https://llamastack-agentic-demo.apps.dgx.eu.arrow.lab"
DEFAULT_NAMESPACE = "agentic-demo"
DEFAULT_DEPLOY = "llamastack"
DEFAULT_K8S_MCP = "http://kubernetes-mcp:8080/mcp"

_INVOKE_K8S_MCP = r"""
import json
import sys
import urllib.request

mcp_url = sys.argv[1]
tool_name = sys.argv[2]
arguments = json.loads(sys.argv[3])


def parse_sse(body: str) -> dict:
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise RuntimeError(f"No MCP SSE data line in response:\n{body[:500]}")


def post(payload: dict, session_id: str | None = None) -> tuple[str | None, dict | None]:
    data = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    req = urllib.request.Request(mcp_url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        session = resp.headers.get("Mcp-Session-Id") or session_id
        body = resp.read().decode()
    if not body.strip():
        return session, None
    return session, parse_sse(body)


session, _ = post(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "call-llama-with-kubernetes", "version": "0"},
        },
    }
)
post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id=session)
_, result = post(
    {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    },
    session_id=session,
)
if "error" in result:
    raise RuntimeError(json.dumps(result["error"]))
content = result.get("result", {}).get("content", [])
if not content:
    print(json.dumps(result.get("result", {})))
else:
    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
    print("\n".join(texts) if texts else json.dumps(content))
"""


def _request_json(
    url: str,
    payload: dict[str, Any],
    *,
    insecure: bool = True,
) -> dict[str, Any]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": "Bearer none",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    ctx = ssl._create_unverified_context() if insecure else None
    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read().decode())


def _invoke_kubernetes_tool(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    namespace: str,
    deploy: str,
    mcp_url: str,
) -> str:
    cmd = [
        "oc",
        "exec",
        "-n",
        namespace,
        f"deploy/{deploy}",
        "--",
        "python3",
        "-c",
        _INVOKE_K8S_MCP,
        mcp_url,
        tool_name,
        json.dumps(arguments),
    ]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def main() -> int:
    base_url = os.environ.get("LLAMA_STACK_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    payload_path = Path(os.environ.get("CHAT_PAYLOAD", DEFAULT_PAYLOAD))
    namespace = os.environ.get("OPENSHIFT_NAMESPACE", DEFAULT_NAMESPACE)
    deploy = os.environ.get("LLAMASTACK_DEPLOY", DEFAULT_DEPLOY)
    mcp_url = os.environ.get("KUBERNETES_MCP_URL", DEFAULT_K8S_MCP)
    insecure = os.environ.get("LLAMA_STACK_INSECURE", "1") != "0"

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    chat_url = f"{base_url}/v1/chat/completions"

    print("=== turn 1: chat/completions ===", file=sys.stderr)
    response = _request_json(chat_url, payload, insecure=insecure)
    print(json.dumps(response, indent=2))

    messages: list[dict[str, Any]] = list(payload["messages"])
    max_turns = int(os.environ.get("MAX_CHAT_TURNS", "10"))

    for turn in range(1, max_turns + 1):
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls = message.get("tool_calls") or []

        messages.append(message)

        if not tool_calls or choice.get("finish_reason") != "tool_calls":
            return 0

        print(
            f"=== invoking {len(tool_calls)} tool(s) via Kubernetes MCP ===",
            file=sys.stderr,
        )
        for tc in tool_calls:
            fn = tc.get("function") or {}
            tool_name = fn.get("name")
            raw_args = fn.get("arguments") or "{}"
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            print(f"--- {tool_name}({args}) ---", file=sys.stderr)
            tool_result = _invoke_kubernetes_tool(
                tool_name,
                args,
                namespace=namespace,
                deploy=deploy,
                mcp_url=mcp_url,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": tool_result,
                }
            )

        chat_payload = {
            "model": payload["model"],
            "messages": messages,
            "tools": payload.get("tools"),
            "tool_choice": payload.get("tool_choice", "auto"),
        }
        print(f"=== turn {turn + 1}: chat/completions ===", file=sys.stderr)
        response = _request_json(chat_url, chat_payload, insecure=insecure)
        print(json.dumps(response, indent=2))

    print(f"error: exceeded MAX_CHAT_TURNS={max_turns}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, subprocess.CalledProcessError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr, file=sys.stderr)
        raise SystemExit(1)
