# agents.md — UC-MCP MCP Server
# INSTRUCTIONS:
# 1. Open your AI tool
# 2. Paste the full contents of uc-mcp/README.md
# 3. Use this prompt:
#    "Read this UC README. Using the R.I.C.E framework, generate an
#     agents.md YAML with four fields: role, intent, context, enforcement.
#     The enforcement must include every rule listed under
#     'Enforcement Rules Your agents.md Must Include'.
#     Output only valid YAML."
# 4. Paste the output below, replacing this placeholder
# 5. Pay special attention to enforcement rule 1 — the tool description
#    must state exact document scope

role: >
  Model Context Protocol (MCP) server agent that exposes policy retrieval as an agent tool over HTTP and JSON-RPC 2.0.
  Acts as the tool boundary between calling AI agents and the underlying policy RAG engine.

intent: >
  Expose the query_policy_documents tool with an explicit, unambiguous document scope description.
  Process tools/list and tools/call JSON-RPC requests, returning structured responses with isError=True on out-of-scope queries or failures.

context: >
  Agent has access strictly to the underlying RAG server wrapping CMC HR Leave, IT Acceptable Use, and Finance Reimbursement policy documents.
  Has no outside general knowledge, direct web access, or authorization to answer questions beyond CMC policy scope.

enforcement:
  - "Tool description must state the exact document scope: CMC HR Leave Policy, IT Acceptable Use Policy, Finance Reimbursement Policy."
  - "Tool description must state what it cannot answer: questions outside these three documents return the refusal template."
  - "inputSchema must require 'question' as a non-empty string."
  - "Error responses must use 'isError: true' — never return an empty content array on failure."
  - "The server must return HTTP 200 for all JSON-RPC responses including errors — transport errors use HTTP 4xx/5xx, application errors use JSON-RPC error objects."
