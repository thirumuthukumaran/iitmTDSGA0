import hashlib
import json
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="Exam MCP Server", docs_url=None, redoc_url=None)

NORMALIZED_EMAIL = "24f3002203@ds.study.iitm.ac.in"
MCP_PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "exam-challenge-mcp", "version": "1.0.0"}

TOOL = {
    "name": "solve_challenge",
    "description": "Returns the required SHA-256 challenge response using the challenge header for this HTTP request.",
    "inputSchema": {
        "type": "object",
        "properties": {}
    }
}


def rpc_result(request_id: Any, result: dict) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "result": result},
        headers={"MCP-Protocol-Version": MCP_PROTOCOL_VERSION},
    )


def rpc_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        },
        headers={"MCP-Protocol-Version": MCP_PROTOCOL_VERSION},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    # MCP Streamable HTTP accepts one JSON-RPC message per POST.
    try:
        body = await request.json()
    except Exception:
        return rpc_error(None, -32700, "Parse error")

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return rpc_error(body.get("id") if isinstance(body, dict) else None,
                         -32600, "Invalid Request")

    method = body.get("method")
    request_id = body.get("id")
    params = body.get("params") or {}

    # Notifications have no id and must not receive a JSON-RPC response.
    if request_id is None:
        if method == "notifications/initialized":
            return Response(status_code=202)
        # Other notifications are accepted without a response too.
        if isinstance(method, str) and method.startswith("notifications/"):
            return Response(status_code=202)
        return Response(status_code=202)

    if method == "initialize":
        requested_version = params.get("protocolVersion", MCP_PROTOCOL_VERSION)
        # The grader can negotiate with this supported version.
        version = requested_version if requested_version == MCP_PROTOCOL_VERSION else MCP_PROTOCOL_VERSION
        return rpc_result(request_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })

    if method == "ping":
        return rpc_result(request_id, {})

    if method == "tools/list":
        return rpc_result(request_id, {"tools": [TOOL]})

    if method == "tools/call":
        name = params.get("name")
        if name != "solve_challenge":
            return rpc_error(request_id, -32602, "Unknown tool")

        # IMPORTANT: challenge is read from the current HTTP request headers,
        # never from params.arguments or the JSON body.
        challenge = request.headers.get("x-exam-challenge")
        if not challenge:
            return rpc_error(request_id, -32602, "Missing X-Exam-Challenge header")

        # The exam contract supplies a 32-character lowercase hex challenge.
        # Do not cache it: every call is computed from that call's own header.
        if len(challenge) != 32 or any(c not in "0123456789abcdef" for c in challenge):
            return rpc_error(request_id, -32602, "Invalid X-Exam-Challenge header")

        digest = hashlib.sha256(
            f"{challenge}:{NORMALIZED_EMAIL}".encode("utf-8")
        ).hexdigest()[:16]

        return rpc_result(request_id, {
            "content": [{"type": "text", "text": digest}],
            "isError": False,
        })

    return rpc_error(request_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
