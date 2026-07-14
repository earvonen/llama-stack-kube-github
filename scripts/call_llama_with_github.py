#!/usr/bin/env python3
"""Multi-turn chat against Llama Stack with inline GitHub tools.

Turn 1: POST /v1/chat/completions (tools in payload).
Turn 2: invoke each tool_call via in-cluster GitHub MCP (oc exec), then POST chat again.
"""
from __future__ import annotations

import argparse
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
DEFAULT_PAYLOAD = ROOT / "chat-payload-github-subset.json"
DEFAULT_BASE_URL = "https://llamastack-agentic-demo.apps.dgx.eu.arrow.lab"
DEFAULT_NAMESPACE = "agentic-demo"
DEFAULT_DEPLOY = "llamastack"
DEFAULT_GITHUB_MCP = "http://github-mcp:8080/"


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


def _parse_mcp_sse(body: str) -> dict[str, Any]:
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise RuntimeError(f"No MCP SSE data line in response:\n{body[:500]}")


def _invoke_github_tool(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    namespace: str,
    deploy: str,
    mcp_url: str,
) -> str:
    mcp_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    cmd = [
        "oc",
        "exec",
        "-n",
        namespace,
        f"deploy/{deploy}",
        "--",
        "curl",
        "-sS",
        "-X",
        "POST",
        mcp_url,
        "-H",
        "Content-Type: application/json",
        "-d",
        json.dumps(mcp_payload),
    ]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    result = _parse_mcp_sse(proc.stdout)
    if "error" in result:
        raise RuntimeError(f"MCP error for {tool_name}: {result['error']}")
    content = result.get("result", {}).get("content", [])
    if not content:
        return json.dumps(result.get("result", {}))
    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "\n".join(texts) if texts else json.dumps(content)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Multi-turn Llama Stack chat with GitHub MCP tools.",
    )
    parser.add_argument(
        "username",
        help="GitHub username to list repositories for",
    )
    args = parser.parse_args()

    base_url = os.environ.get("LLAMA_STACK_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    payload_path = Path(os.environ.get("CHAT_PAYLOAD", DEFAULT_PAYLOAD))
    namespace = os.environ.get("OPENSHIFT_NAMESPACE", DEFAULT_NAMESPACE)
    deploy = os.environ.get("LLAMASTACK_DEPLOY", DEFAULT_DEPLOY)
    mcp_url = os.environ.get("GITHUB_MCP_URL", DEFAULT_GITHUB_MCP)
    insecure = os.environ.get("LLAMA_STACK_INSECURE", "1") != "0"

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    for msg in payload.get("messages", []):
        if msg.get("role") == "user":
            msg["content"] = f"List all the repos of {args.username}."
            break
    chat_url = f"{base_url}/v1/chat/completions"

    print("=== turn 1: chat/completions ===", file=sys.stderr)
    turn1 = _request_json(chat_url, payload, insecure=insecure)
    print(json.dumps(turn1, indent=2))

    choice = (turn1.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    tool_calls = message.get("tool_calls") or []
    if not tool_calls:
        return 0

    messages: list[dict[str, Any]] = list(payload["messages"])
    messages.append(message)

    print(f"=== invoking {len(tool_calls)} tool(s) via GitHub MCP ===", file=sys.stderr)
    for tc in tool_calls:
        fn = tc.get("function") or {}
        tool_name = fn.get("name")
        raw_args = fn.get("arguments") or "{}"
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        print(f"--- {tool_name}({args}) ---", file=sys.stderr)
        tool_result = _invoke_github_tool(
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

    turn2_payload = {
        "model": payload["model"],
        "messages": messages,
        "tools": payload.get("tools"),
        "tool_choice": payload.get("tool_choice", "auto"),
    }

    print("=== turn 2: chat/completions (with tool results) ===", file=sys.stderr)
    turn2 = _request_json(chat_url, turn2_payload, insecure=insecure)
    print(json.dumps(turn2, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, subprocess.CalledProcessError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
