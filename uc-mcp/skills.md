# skills.md — UC-MCP MCP Server
# INSTRUCTIONS:
# 1. Open your AI tool
# 2. Paste the full contents of uc-mcp/README.md
# 3. Use this prompt:
#    "Read this UC README. Generate a skills.md YAML defining the two
#     skills: query_policy_documents and serve_mcp. Each skill needs:
#     name, description, input, output, error_handling.
#     error_handling must address the failure mode in the README.
#     Output only valid YAML."
# 4. Paste the output below, replacing this placeholder

skills:
  - name: query_policy_documents
    description: Invoke the RAG server to answer questions grounded in CMC HR, IT, and Finance policy documents.
    input: Question (string).
    output: Dict in MCP content format with keys content (list with type and text) and isError (boolean).
    error_handling: If question is out of scope or RAG server returns refused=True, return refusal text with isError=True. If exception occurs, return error message with isError=True. Never return empty content array.

  - name: serve_mcp
    description: Serve JSON-RPC 2.0 requests over plain HTTP POST endpoint, supporting tools/list and tools/call methods.
    input: HTTP POST request with JSON-RPC 2.0 body containing method, params, and id.
    output: HTTP 200 response with JSON-RPC 2.0 result or error payload.
    error_handling: If method unknown, return JSON-RPC error code -32601 (Method not found). If JSON malformed, return JSON-RPC error code -32700 (Parse error). Always return HTTP 200 with error details in JSON-RPC payload.
