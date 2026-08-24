"""
UC-MCP — mcp_server.py
Plain HTTP MCP Server — Starter File

Build this using your AI coding tool:
1. Share agents.md, skills.md, and uc-mcp/README.md with your AI tool
2. Ask it to implement this file following the MCP protocol
   described in the README
3. Run with: python3 mcp_server.py --port 8765
4. Test with: python3 test_client.py --port 8765

Protocol: JSON-RPC 2.0 over HTTP POST
No external dependencies beyond Python stdlib.

Methods to implement:
  tools/list  — return the tool definition for query_policy_documents
  tools/call  — execute query_policy_documents, return JSON-RPC response
"""

import json
import argparse
import sys
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

# Import RAG — uses stub by default, swap to rag_server once yours works
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../uc-rag"))
try:
    # Try participant's rag_server first
    from rag_server import query as rag_query
    print("[mcp_server] Using participant rag_server.py")
except (ImportError, NotImplementedError):
    # Fall back to stub
    from stub_rag import query as rag_query
    print("[mcp_server] Using stub_rag.py (fallback)")

# Import LLM adapter
from llm_adapter import call_llm


# ── TOOL DEFINITION ──────────────────────────────────────────────────────────
TOOL_DEFINITION = {
    "name": "query_policy_documents",
    "description": (
        "Answers questions about City Municipal Corporation (CMC) policy documents only: "
        "CMC HR Leave Policy, IT Acceptable Use Policy, and Finance Reimbursement Policy. "
        "Returns cited answers grounded in retrieved document chunks. Returns a refusal "
        "with isError: true for questions outside these three documents (such as budget forecasts)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The policy question to answer",
            }
        },
        "required": ["question"],
    },
}


# ── SKILL: query_policy_documents ────────────────────────────────────────────
def query_policy_documents(question: str) -> dict:
    """
    Call the RAG server with the question.
    Return MCP content format: {"content": [...], "isError": bool}

    Error handling:
    - If RAG refuses (no chunks above threshold) → isError: True
    - If RAG raises exception → isError: True with error message
    """
    if not question or not isinstance(question, str) or not question.strip():
        return {
            "content": [{"type": "text", "text": "Error: question must be a non-empty string."}],
            "isError": True
        }

    try:
        result = rag_query(question.strip(), llm_call=call_llm)
        is_refused = result.get("refused", False)
        answer_text = result.get("answer", "")
        
        return {
            "content": [{"type": "text", "text": answer_text}],
            "isError": bool(is_refused)
        }
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error querying policy documents: {str(e)}"}],
            "isError": True
        }


# ── SKILL: serve_mcp ─────────────────────────────────────────────────────────
class MCPHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler implementing JSON-RPC 2.0.
    Handles POST requests to / with JSON-RPC body.
    """

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        # Parse JSON
        try:
            req = json.loads(post_data.decode("utf-8"))
        except Exception:
            self._send_jsonrpc_response(None, error={"code": -32700, "message": "Parse error"})
            return

        req_id = req.get("id", 1)
        method = req.get("method", "")
        params = req.get("params", {})

        if method == "tools/list":
            self._send_jsonrpc_response(req_id, result={"tools": [TOOL_DEFINITION]})
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            if tool_name == "query_policy_documents":
                question = arguments.get("question", "")
                result = query_policy_documents(question)
                self._send_jsonrpc_response(req_id, result=result)
            else:
                self._send_jsonrpc_response(req_id, error={"code": -32601, "message": f"Tool '{tool_name}' not found"})
        else:
            self._send_jsonrpc_response(req_id, error={"code": -32601, "message": f"Method '{method}' not found"})

    def _send_jsonrpc_response(self, req_id, result=None, error=None):
        response = {
            "jsonrpc": "2.0",
            "id": req_id
        }
        if error:
            response["error"] = error
        else:
            response["result"] = result

        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress default HTTP logging
        print(f"[mcp_server] {args[0]} {args[1]}")


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="UC-MCP Plain HTTP MCP Server")
    parser.add_argument("--port", type=int, default=8765,
                        help="Port to listen on (default: 8765)")
    args = parser.parse_args()

    server = HTTPServer(("localhost", args.port), MCPHandler)
    print(f"[mcp_server] MCP server running on http://localhost:{args.port}")
    print(f"[mcp_server] Test with: python test_client.py --port {args.port}")
    print(f"[mcp_server] Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[mcp_server] Stopped.")


if __name__ == "__main__":
    main()
