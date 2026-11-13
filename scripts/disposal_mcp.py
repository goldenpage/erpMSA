"""A loopback MCP endpoint for one investigation's scoped read tools."""

import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
from threading import Thread


MCP_TOKEN_ENV = "ERPMSA_MCP_TOKEN"


class InvestigationError(Exception):
    pass


DISPOSAL_TOOLS = [
    {
        "name": "get_disposal",
        "description": "선택된 폐기의 상세를 조회한다. 재고 원장을 조회하기 전에 사용한다.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "get_stock_movements",
        "description": "선택된 폐기의 식자재 원장 한 페이지를 조회하고 차감 근거를 대조한다. page는 0부터 시작한다.",
        "inputSchema": {
            "type": "object", "properties": {"page": {"type": "integer", "minimum": 0}},
            "required": ["page"], "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
]


class ReadOnlyMcp:
    def __init__(self, investigation, tools):
        self.investigation = investigation
        self.tools = tools
        self.secret = secrets.token_urlsafe(32)
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def log_message(self, *args):
                pass

            def reply(self, status, body=None):
                payload = b"" if body is None else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                self.reply(405)

            def do_POST(self):
                authorization = self.headers.get("Authorization", "")
                if self.path != "/mcp" or self.headers.get("Origin") or not hmac.compare_digest(
                    authorization.encode(), f"Bearer {endpoint.secret}".encode()
                ):
                    self.reply(403)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 65536:
                        raise ValueError()
                    message = json.loads(self.rfile.read(size))
                    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                        raise ValueError()
                except (ValueError, RecursionError, OSError):
                    self.reply(400)
                    return
                if "id" not in message:
                    self.reply(202)
                    return
                result = endpoint.dispatch(message)
                self.reply(200, {"jsonrpc": "2.0", "id": message["id"], **result})

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def config(self):
        return {
            "type": "remote", "url": f"http://127.0.0.1:{self.server.server_port}/mcp",
            "oauth": False, "codemode": False,
            "headers": {"Authorization": f"Bearer {{env:{MCP_TOKEN_ENV}}}"},
        }

    def dispatch(self, message):
        method = message.get("method")
        if method == "initialize":
            return {"result": {
                "protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                "serverInfo": {"name": "erp-investigation-reader", "version": "1.0.0"},
            }}
        if method == "ping":
            return {"result": {}}
        if method == "tools/list":
            return {"result": {"tools": self.tools}}
        if method == "tools/call":
            params = message.get("params")
            if not isinstance(params, dict):
                return {"error": {"code": -32602, "message": "Invalid parameters"}}
            result = self.investigation.call(params.get("name"), params.get("arguments", {}))
            return {"result": {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "isError": "error" in result,
            }}
        return {"error": {"code": -32601, "message": "Method not allowed"}}
