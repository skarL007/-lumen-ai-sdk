"""Small stdio MCP server exposing LumenAI audit harness artifacts."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("LUMEN_AUDIT_ROOT", Path(__file__).resolve().parents[2])).resolve()

RESOURCES = {
    "lumen-audit://context": ROOT / "harness" / "context" / "project-context.md",
    "lumen-audit://report": ROOT / "harness" / "reports" / "audit-data.json",
    "lumen-audit://dashboard": ROOT / "harness" / "dashboard" / "index.html",
    "lumen-audit://skill": ROOT / "harness" / "skills" / "lumen-ai-audit" / "SKILL.md",
}


def _read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        key, _, value = line.decode("ascii").partition(":")
        headers[key.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def _write_message(payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def _report() -> dict[str, Any]:
    path = RESOURCES["lumen-audit://report"]
    if not path.exists():
        return {"status": "missing", "hint": "Run harness/scripts/run-audit.ps1 first."}
    return json.loads(path.read_text(encoding="utf-8"))


def _tools_list() -> list[dict[str, Any]]:
    return [
        {
            "name": "audit_summary",
            "description": "Return overall score, aspect scores, gate status, and report path.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_findings",
            "description": "List audit findings, optionally filtered by severity or aspect.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string"},
                    "aspect": {"type": "string"},
                },
            },
        },
    ]


def _call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    data = _report()
    if name == "audit_summary":
        summary = {
            "generated_at": data.get("generated_at"),
            "repo": data.get("repo"),
            "overall_score": data.get("overall_score"),
            "aspects": data.get("aspects"),
            "gates": data.get("gates"),
            "dashboard": str(ROOT / "harness" / "dashboard" / "index.html"),
        }
        return {"content": [{"type": "text", "text": json.dumps(summary, indent=2)}]}
    if name == "list_findings":
        findings = data.get("findings", [])
        severity = (args.get("severity") or "").upper()
        aspect = (args.get("aspect") or "").lower()
        if severity:
            findings = [f for f in findings if f.get("severity") == severity]
        if aspect:
            findings = [f for f in findings if aspect in f.get("aspect", "").lower()]
        return {"content": [{"type": "text", "text": json.dumps(findings, indent=2)}]}
    raise ValueError(f"Unknown tool: {name}")


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "notifications/initialized":
        return None
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "lumen-ai-audit", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": _tools_list()}
        elif method == "tools/call":
            params = message.get("params") or {}
            result = _call_tool(params.get("name", ""), params.get("arguments") or {})
        elif method == "resources/list":
            result = {
                "resources": [
                    {"uri": uri, "name": uri.rsplit("/", 1)[-1], "mimeType": "text/plain"}
                    for uri in RESOURCES
                ]
            }
        elif method == "resources/read":
            uri = (message.get("params") or {}).get("uri")
            path = RESOURCES.get(uri)
            if path is None:
                raise ValueError(f"Unknown resource: {uri}")
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            result = {"contents": [{"uri": uri, "mimeType": "text/plain", "text": text}]}
        else:
            raise ValueError(f"Unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    except Exception as exc:  # MCP errors must be returned, not raised.
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32000, "message": str(exc)}}


def main() -> int:
    while True:
        message = _read_message()
        if message is None:
            return 0
        response = _handle(message)
        if response is not None and "id" in message:
            _write_message(response)


if __name__ == "__main__":
    raise SystemExit(main())

