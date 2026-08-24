# skills.md — UC-RAG RAG Server
# INSTRUCTIONS:
# 1. Open your AI tool
# 2. Paste the full contents of uc-rag/README.md
# 3. Use this prompt:
#    "Read this UC README. Generate a skills.md YAML defining the two
#     skills: chunk_documents and retrieve_and_answer. Each skill needs:
#     name, description, input, output, error_handling.
#     error_handling must address the failure modes in the README.
#     Output only valid YAML."
# 4. Paste the output below, replacing this placeholder
# 5. Verify error_handling addresses all three failure modes

skills:
  - name: chunk_documents
    description: Load all policy documents from directory and split into sentence-bounded chunks of maximum 400 tokens without splitting mid-sentence.
    input: File path to policy documents directory containing .txt files.
    output: List of chunk dicts, each with keys doc_name, chunk_index, text, and id.
    error_handling: If directory or file missing, log warning and skip. Never split mid-sentence. If a single sentence exceeds max_tokens, preserve sentence intact to avoid cutting obligations.

  - name: retrieve_and_answer
    description: Embed query, retrieve top-3 most relevant chunks from vector collection, filter by cosine similarity threshold 0.6, and synthesize grounded answer with chunk citations.
    input: Query string, optional llm_call callable, top_k integer (default 3), threshold float (default 0.6).
    output: Dict with keys answer, cited_chunks (list of doc_name, chunk_index, score, text), and refused boolean.
    error_handling: If no chunks pass similarity threshold 0.6, return refusal template with refused=True. Never hallucinate answers outside retrieved context. Never blend across disparate policy documents.
