"""Backward-compatible entrypoint for RAG utilities.

Implementation details were split into the rag_core package to keep indexing,
retrieval, ICD suggestion, and prompt-context composition easier to maintain.
"""

if __package__:
    from .rag_core import (  # noqa: F401
        DEFAULT_BATCH_SIZE,
        DEFAULT_CHROMA_PATH,
        DEFAULT_CHUNK_OVERLAP,
        DEFAULT_CHUNK_SIZE,
        DEFAULT_EMBED_MODEL,
        DEFAULT_ICD_CODES_PATH,
        DEFAULT_KB_PATH,
        build_context_block,
        get_relevant_context,
        load_existing_vectorstore,
        setup_knowledge_base,
        suggest_icd_codes_local,
    )
else:
    from rag_core import (  # noqa: F401
        DEFAULT_BATCH_SIZE,
        DEFAULT_CHROMA_PATH,
        DEFAULT_CHUNK_OVERLAP,
        DEFAULT_CHUNK_SIZE,
        DEFAULT_EMBED_MODEL,
        DEFAULT_ICD_CODES_PATH,
        DEFAULT_KB_PATH,
        build_context_block,
        get_relevant_context,
        load_existing_vectorstore,
        setup_knowledge_base,
        suggest_icd_codes_local,
    )

__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_CHROMA_PATH",
    "DEFAULT_CHUNK_OVERLAP",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_EMBED_MODEL",
    "DEFAULT_ICD_CODES_PATH",
    "DEFAULT_KB_PATH",
    "build_context_block",
    "get_relevant_context",
    "load_existing_vectorstore",
    "setup_knowledge_base",
    "suggest_icd_codes_local",
]
