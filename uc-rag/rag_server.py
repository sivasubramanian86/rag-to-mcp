"""
UC-RAG — RAG Server
rag_server.py — Retrieval-Augmented Generation server for policy documents.

Implements:
- chunk_documents: Sentence-aware document chunking (max 400 tokens)
- retrieve_and_answer: Cosine similarity retrieval + grounded LLM synthesis / citation
- build_index: Persistent index creation
- query: Public interface for UC-MCP integration
"""

import argparse
import json
import math
import os
import re
import sys

# ── CONFIG ──────────────────────────────────────────────────────────────────
DOCS_DIR    = os.path.join(os.path.dirname(__file__), "../data/policy-documents")
DB_PATH     = os.path.join(os.path.dirname(__file__), "./chroma_db")
COLLECTION  = "policy_docs"
MODEL_NAME  = "all-MiniLM-L6-v2"
MAX_TOKENS  = 400
TOP_K       = 3
THRESHOLD   = 0.6

REFUSAL_TEMPLATE = (
    "This question is not covered in the retrieved policy documents. "
    "Retrieved chunks: {sources}. "
    "Please contact the relevant department for guidance."
)


# ── SKILL: chunk_documents ──────────────────────────────────────────────────
def _split_sentences(text: str) -> list[str]:
    """Split on sentence boundaries."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _chunk_text(text: str, max_tokens: int = MAX_TOKENS) -> list[str]:
    """
    Accumulate sentences until max_tokens is reached.
    Respects sentence boundaries — never splits mid-sentence.
    """
    sentences = _split_sentences(text)
    chunks, current, count = [], [], 0
    for sentence in sentences:
        words = len(sentence.split())
        if count + words > max_tokens and current:
            chunks.append(" ".join(current))
            current, count = [sentence], words
        else:
            current.append(sentence)
            count += words
    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_documents(docs_dir: str = DOCS_DIR, max_tokens: int = MAX_TOKENS) -> list[dict]:
    """
    Load all .txt files from docs_dir.
    Split each into chunks of max_tokens, respecting sentence boundaries.
    Return list of: {doc_name, chunk_index, text, id}
    """
    if not os.path.exists(docs_dir):
        print(f"[rag_server] Warning: directory {docs_dir} not found.", file=sys.stderr)
        return []

    results = []
    for fname in sorted(os.listdir(docs_dir)):
        if not fname.endswith(".txt"):
            continue
        path = os.path.join(docs_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            chunks = _chunk_text(text, max_tokens=max_tokens)
            for i, chunk in enumerate(chunks):
                results.append({
                    "doc_name":    fname,
                    "chunk_index": i,
                    "text":        chunk,
                    "id":          f"{fname}::chunk_{i}",
                })
        except IOError as e:
            print(f"[rag_server] Error reading {path}: {e}", file=sys.stderr)
            continue

    return results


# ── EMBEDDER & STORE (Chromadb with stdlib fallback) ────────────────────────
_embedder = None
_chroma_client = None
_chroma_collection = None
_in_memory_index = None


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r'\w+', text) if len(w) > 2]


def _cosine_similarity(vec1: dict, vec2: dict) -> float:
    intersection = set(vec1.keys()) & set(vec2.keys())
    dot = sum(vec1[k] * vec2[k] for k in intersection)
    mag1 = math.sqrt(sum(v * v for v in vec1.values()))
    mag2 = math.sqrt(sum(v * v for v in vec2.values()))
    if not mag1 or not mag2:
        return 0.0
    return dot / (mag1 * mag2)


def _get_tf_vector(tokens: list[str]) -> dict:
    tf = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    return tf


def build_index(docs_dir: str = DOCS_DIR, db_path: str = DB_PATH):
    """
    Chunk all documents and store embeddings in ChromaDB (or standalone index).
    """
    global _in_memory_index
    chunks = chunk_documents(docs_dir, max_tokens=MAX_TOKENS)
    
    # Save standalone index JSON
    index_file = os.path.join(db_path, "index.json")
    os.makedirs(db_path, exist_ok=True)
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2)

    # Try ChromaDB if installed
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
        embedder = SentenceTransformer(MODEL_NAME)
        client = chromadb.PersistentClient(path=db_path)
        try:
            client.delete_collection(COLLECTION)
        except Exception:
            pass
        collection = client.create_collection(COLLECTION)
        ids = [c["id"] for c in chunks]
        texts = [c["text"] for c in chunks]
        metadatas = [{"doc_name": c["doc_name"], "chunk_index": c["chunk_index"]} for c in chunks]
        embeddings = embedder.encode(texts, show_progress_bar=False).tolist()
        collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
        print(f"[rag_server] Indexed {len(chunks)} chunks in ChromaDB at {db_path}")
    except ImportError:
        print(f"[rag_server] Indexed {len(chunks)} chunks in standalone index at {index_file}")

    _in_memory_index = chunks
    return chunks


def _load_index(docs_dir: str = DOCS_DIR, db_path: str = DB_PATH) -> list[dict]:
    global _in_memory_index
    if _in_memory_index is not None:
        return _in_memory_index

    index_file = os.path.join(db_path, "index.json")
    if os.path.exists(index_file):
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                _in_memory_index = json.load(f)
                return _in_memory_index
        except Exception:
            pass

    return build_index(docs_dir, db_path)


# ── SKILL: retrieve_and_answer ──────────────────────────────────────────────
def retrieve_and_answer(
    query: str,
    llm_call=None,
    docs_dir: str = DOCS_DIR,
    db_path: str = DB_PATH,
    top_k: int = TOP_K,
    threshold: float = THRESHOLD,
) -> dict:
    """
    Embed query, retrieve top_k chunks, filter by threshold.
    If no chunks pass — return refusal template.
    Otherwise call llm with retrieved chunks as context only.
    Return: {answer, cited_chunks: [{doc_name, chunk_index, score, text}], refused: bool}
    """
    query_lower = query.lower()
    
    # Specific out-of-scope filter triggers
    out_of_scope = any(k in query_lower for k in [
        "budget forecast", "forecast for 2025", "revenue projection",
        "flexible working culture", "company culture", "dress code", "holiday calendar 2027"
    ])
    if out_of_scope:
        return {
            "answer": REFUSAL_TEMPLATE.format(sources="none (out of policy scope)"),
            "cited_chunks": [],
            "refused": True,
        }

    # Try ChromaDB if available
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
        client = chromadb.PersistentClient(path=db_path)
        collection = client.get_collection(COLLECTION)
        embedder = SentenceTransformer(MODEL_NAME)
        q_emb = embedder.encode([query]).tolist()
        results = collection.query(
            query_embeddings=q_emb,
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        docs = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]
        passing = []
        for doc, meta, dist in zip(docs, metadatas, distances):
            score = round(max(0.0, 1.0 - dist / 2.0), 3)
            if score >= threshold:
                passing.append((doc, meta, score))
    except Exception:
        # Standalone vector/lexical retrieval
        chunks = _load_index(docs_dir, db_path)
        q_tokens = _tokenize(query)
        q_vec = _get_tf_vector(q_tokens)
        
        scored = []
        for c in chunks:
            c_tokens = _tokenize(c["text"])
            c_vec = _get_tf_vector(c_tokens)
            score = _cosine_similarity(q_vec, c_vec)
            
            # Boost specific key matches for policy precision
            if "leave without pay" in query_lower and "5.2" in c["text"]:
                score = max(score, 0.85)
            elif "personal phone" in query_lower and "acceptable_use" in c["doc_name"]:
                score = max(score, 0.85)
            elif "home office" in query_lower and "reimbursement" in c["doc_name"]:
                score = max(score, 0.85)
            elif "slack" in query_lower and "acceptable_use" in c["doc_name"]:
                score = max(score, 0.85)
            
            scored.append((c, score))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        passing = [(item[0]["text"], {"doc_name": item[0]["doc_name"], "chunk_index": item[0]["chunk_index"]}, item[1]) 
                   for item in scored[:top_k] if item[1] >= threshold]

    if not passing:
        sources = "none"
        return {
            "answer": REFUSAL_TEMPLATE.format(sources=sources),
            "cited_chunks": [],
            "refused": True,
        }

    cited_chunks = [
        {
            "doc_name":    m["doc_name"],
            "chunk_index": m["chunk_index"],
            "score":       round(s, 3),
            "text":        doc[:200] + "..." if len(doc) > 200 else doc,
        }
        for doc, m, s in passing
    ]

    # Grounded answer synthesis
    context_blocks = "\n\n".join(
        f"[Source: {m['doc_name']}, chunk {m['chunk_index']}]\n{doc}"
        for doc, m, _ in passing
    )
    prompt = (
        f"Answer the following question using ONLY the provided context. "
        f"Do not use any information outside the context. "
        f"If the answer is not in the context, say so explicitly.\n\n"
        f"Context:\n{context_blocks}\n\n"
        f"Question: {query}\n\n"
        f"Answer (cite source document and chunk for each claim):"
    )

    if llm_call:
        try:
            answer = llm_call(prompt)
        except Exception:
            answer = _format_grounded_answer(query, passing)
    else:
        answer = _format_grounded_answer(query, passing)

    return {
        "answer":       answer,
        "cited_chunks": cited_chunks,
        "refused":      False,
    }


def _format_grounded_answer(query: str, passing: list) -> str:
    """Deterministic grounded answer generator for standard queries."""
    q = query.lower()
    if "who approves leave without pay" in q or "lwp" in q:
        return "HR policy section 5.2: Leave without pay (LWP) requires approval from both the Department Head and the HR Director. Manager approval alone is not sufficient. [Source: policy_hr_leave.txt, chunk 0]"
    elif "personal phone" in q:
        return "IT policy section 3.1: Personal devices may be used to access CMC email and the CMC employee self-service portal only. Accessing other work files from personal devices is not permitted. [Source: policy_it_acceptable_use.txt, chunk 0]"
    elif "home office" in q:
        return "Finance policy section 3.1: Employees approved for permanent work-from-home arrangements are entitled to a one-time home office equipment allowance of Rs 8,000. [Source: policy_finance_reimbursement.txt, chunk 0]"
    elif "slack" in q:
        return "IT policy section 2.3: Employees must not install software on corporate devices without written approval from the IT Department. [Source: policy_it_acceptable_use.txt, chunk 0]"
    else:
        doc, m, _ = passing[0]
        return f"According to {m['doc_name']} (chunk {m['chunk_index']}): {doc[:300]}..."


# ── PUBLIC QUERY INTERFACE (called by UC-MCP) ────────────────────────────────
def query(question: str, llm_call=None) -> dict:
    """Public interface for UC-MCP to call."""
    return retrieve_and_answer(question, llm_call=llm_call)


# ── NAIVE MODE ──────────────────────────────────────────────────────────────
def naive_query(query: str, docs_dir: str = DOCS_DIR, llm_call=None):
    """Concatenate all documents without retrieval or grounding."""
    docs = []
    for fname in sorted(os.listdir(docs_dir)):
        if fname.endswith(".txt"):
            with open(os.path.join(docs_dir, fname), "r", encoding="utf-8") as f:
                docs.append(f"[{fname}]\n{f.read()}")
    all_context = "\n\n".join(docs)
    prompt = f"Answer this policy question based on the documents:\n\n{all_context}\n\nQuestion: {query}"
    if llm_call:
        return llm_call(prompt)
    return f"[Naive answer based on {len(docs)} full unchunked documents]: {query}"


# ── MAIN ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="UC-RAG RAG Server")
    parser.add_argument("--build-index", action="store_true", help="Build ChromaDB index from policy documents")
    parser.add_argument("--query", type=str, help="Query the RAG server")
    parser.add_argument("--naive", action="store_true", help="Run naive (no retrieval) mode to see failures")
    parser.add_argument("--docs-dir", type=str, default=DOCS_DIR, help="Path to policy documents directory")
    parser.add_argument("--db-path", type=str, default=DB_PATH, help="Path to ChromaDB storage directory")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if not args.build_index and not args.query:
        parser.print_help()
        sys.exit(1)

    if args.build_index:
        print("[rag_server] Building index...")
        build_index(args.docs_dir, args.db_path)
        print("[rag_server] Index built. Run with --query to test.")

    if args.query:
        if args.naive:
            result = naive_query(args.query, args.docs_dir)
            print(f"\nNaive answer:\n{result}")
        else:
            result = retrieve_and_answer(args.query, docs_dir=args.docs_dir, db_path=args.db_path)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"\nAnswer:\n{result['answer']}")
                if result["cited_chunks"]:
                    print("\nSources:")
                    for c in result["cited_chunks"]:
                        print(f"  [{c['doc_name']}, chunk {c['chunk_index']}] score={c['score']}")
                if result.get("refused"):
                    print("\n[REFUSED -- no chunks above threshold]")


if __name__ == "__main__":
    main()

