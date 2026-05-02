from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional
import math
import re

from langchain_core.documents import Document

from .config import (
    CATEGORY_ADJUST_MED_MONOGRAPH,
    CATEGORY_ADJUST_SYMPTOM_CLINICAL,
    CATEGORY_ADJUST_SYMPTOM_DDI,
    CATEGORY_ADJUST_SYMPTOM_LAB,
    CATEGORY_ADJUST_SYMPTOM_MONOGRAPH,
    CATEGORY_PRIORITY_MED_MONOGRAPH,
    CATEGORY_PRIORITY_SYMPTOM_CLINICAL,
    CATEGORY_PRIORITY_SYMPTOM_DDI,
    CATEGORY_PRIORITY_SYMPTOM_LAB,
    DEFAULT_ICD_CODES_PATH,
    RETRIEVAL_HITS_WEIGHT,
    RETRIEVAL_LEXICAL_WEIGHT,
    RETRIEVAL_MAX_MERGED_DOCS,
    RETRIEVAL_MAX_PER_CATEGORY_MIN,
    RETRIEVAL_BM25_WEIGHT,
    RETRIEVAL_POOL_K_MIN,
    RETRIEVAL_POOL_K_MULTIPLIER,
    RETRIEVAL_RRF_K,
    RETRIEVAL_RRF_WEIGHT,
    RETRIEVAL_SCORE_NORM_WEIGHT,
    RETRIEVAL_SEMANTIC_WEIGHT,
    RETRIEVAL_TARGETED_K_MIN,
    SECTION_PENALTY,
    SOURCE_BONUS_GENERAL,
    SOURCE_BONUS_SYMPTOM,
    SYMPTOM_BONUS_MAX,
    SYMPTOM_BONUS_PER_HIT,
)
from .icd import suggest_icd_codes_local
from .text_processing import (
    build_retrieval_queries,
    classify_retrieval_intent,
    doc_category,
    extract_ddi_pair_terms,
    extract_query_medication_terms,
    extract_symptom_terms_from_text,
    lexical_overlap_ratio,
    normalize_symptom_key,
    truncate_snippet,
)


_LEXICAL_INDEX_CACHE: dict[int, dict[str, Any]] = {}

_BM25_STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "have", "has", "had", "were", "was",
    "are", "you", "your", "they", "them", "their", "what", "when", "where", "which", "while",
    "been", "into", "about", "after", "before", "more", "most", "some", "just", "very", "does",
    "did", "doing", "would", "could", "should", "can", "will", "also", "there", "here", "than",
    "then", "over", "under", "between", "doctor", "patient", "today", "please", "thank", "thanks",
}

_NON_CLINICAL_MARKERS = {
    "flood", "wildfire", "sexual assault", "consent", "parking", "cell phone", "earthquake",
    "hurricane", "tsunami", "firefighters", "prairie", "disaster preparedness",
}

_MEDICAL_MARKERS = {
    "pain", "headache", "migraine", "nausea", "vomit", "fatigue", "sleep", "insomnia", "abdomen",
    "abdominal", "cramp", "thyroid", "tsh", "blood", "ferritin", "ibuprofen", "drug", "dose",
    "diagnosis", "treatment", "symptom", "clinical", "icd", "dyspepsia", "irritable", "bowel",
}


def _looks_english(text: str) -> bool:
    """Heuristic: return True when text appears to be primarily English.

    Lightweight check suitable for filtering noisy multilingual KB entries.
    """
    if not text:
        return False
    # proportion of ASCII characters
    total = len(text)
    ascii_count = sum(1 for c in text if ord(c) < 128)
    if ascii_count / max(1, total) < 0.8:
        return False
    lower = text.lower()
    # quick negative check for common Spanish function words that indicate non-English
    spanish_markers = [" el ", " la ", " que ", " y ", " para ", " los ", " las ", " con ", " por "]
    if any(m in lower for m in spanish_markers):
        # allow short strings that may contain these sequences incidentally
        if total > 120:
            return False
    return True


def _tokenize_bm25(text: str) -> list[str]:
    if not text:
        return []
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in toks if len(t) >= 3 and t not in _BM25_STOPWORDS]


def _looks_clinical_enough(text: str, metadata: dict[str, Any]) -> bool:
    lower = (text or "").lower()
    for marker in _NON_CLINICAL_MARKERS:
        if marker in lower:
            return False

    source = str(metadata.get("source", "")).lower()
    if any(k in source for k in ("ddi", "clinical", "drug", "medline", "icd", "lab")):
        return True

    return any(marker in lower for marker in _MEDICAL_MARKERS)


def _build_vectorstore_lexical_index(vectorstore: Any) -> Optional[dict[str, Any]]:
    cache_key = id(vectorstore)
    cached = _LEXICAL_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        collection = getattr(vectorstore, "_collection", None)
        if collection is None:
            return None
        payload = collection.get(include=["documents", "metadatas"])
        raw_docs = payload.get("documents") or []
        raw_meta = payload.get("metadatas") or []
    except Exception:
        return None

    docs: list[Document] = []
    term_freqs: list[dict[str, int]] = []
    doc_lens: list[int] = []
    doc_freq: dict[str, int] = {}

    for idx, content in enumerate(raw_docs):
        text = str(content or "").strip()
        if not text:
            continue

        tokens = _tokenize_bm25(text)
        if not tokens:
            continue

        tf: dict[str, int] = {}
        for tok in tokens:
            tf[tok] = tf.get(tok, 0) + 1
        for tok in tf:
            doc_freq[tok] = doc_freq.get(tok, 0) + 1

        meta = raw_meta[idx] if idx < len(raw_meta) and isinstance(raw_meta[idx], dict) else {}
        docs.append(Document(page_content=text, metadata=meta))
        term_freqs.append(tf)
        doc_lens.append(len(tokens))

    doc_count = len(docs)
    if doc_count == 0:
        return None

    idf = {
        tok: math.log((doc_count - df + 0.5) / (df + 0.5) + 1.0)
        for tok, df in doc_freq.items()
    }
    avg_doc_len = sum(doc_lens) / doc_count

    index = {
        "docs": docs,
        "term_freqs": term_freqs,
        "doc_lens": doc_lens,
        "idf": idf,
        "avg_doc_len": avg_doc_len,
    }
    _LEXICAL_INDEX_CACHE[cache_key] = index
    return index


def _bm25_score_from_tf(
    query_tokens: list[str],
    tf: dict[str, int],
    idf: dict[str, float],
    doc_len: int,
    avg_doc_len: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not query_tokens or not tf:
        return 0.0

    score = 0.0
    norm = 1 - b + b * (doc_len / max(1.0, avg_doc_len))
    for q in query_tokens:
        if q not in idf:
            continue
        f = tf.get(q, 0)
        if f <= 0:
            continue
        denom = f + k1 * norm
        score += idf[q] * ((f * (k1 + 1)) / (denom if denom else 1.0))
    return score


def _lexical_search_from_vectorstore(
    query: str,
    vectorstore: Any,
    k: int,
    query_is_english: bool,
) -> list[tuple[Document, float]]:
    index = _build_vectorstore_lexical_index(vectorstore)
    if index is None:
        return []

    query_tokens = _tokenize_bm25(query)
    if not query_tokens:
        return []

    docs = index["docs"]
    term_freqs = index["term_freqs"]
    doc_lens = index["doc_lens"]
    idf = index["idf"]
    avg_doc_len = index["avg_doc_len"]

    salient_query_tokens = [tok for tok in query_tokens if idf.get(tok, 0.0) >= 2.0 and len(tok) >= 4]

    scored: list[tuple[Document, float]] = []
    for i, doc in enumerate(docs):
        if query_is_english and not _looks_english(doc.page_content):
            continue
        if not _looks_clinical_enough(doc.page_content, doc.metadata):
            continue

        if salient_query_tokens:
            tf = term_freqs[i]
            if not any(tok in tf for tok in salient_query_tokens):
                continue

        s = _bm25_score_from_tf(query_tokens, term_freqs[i], idf, doc_lens[i], avg_doc_len)
        if s > 0:
            scored.append((doc, float(s)))

    if not scored:
        return []

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:k]


def similarity_search_with_optional_filter(
    vectorstore: Any,
    query: str,
    k: int,
    where: Optional[dict] = None,
) -> list:
    """Run similarity search, using metadata filter only when supported by the backend."""
    try:
        if where:
            return vectorstore.similarity_search_with_score(query, k=k, filter=where)
        return vectorstore.similarity_search_with_score(query, k=k)
    except TypeError:
        return vectorstore.similarity_search_with_score(query, k=k)
    except Exception:
        return []


def get_relevant_context(
    query: str,
    vectorstore: Any,
    final_k: int = 5,
    retrieve_k: int = 8,
    max_queries: int = 4,
    min_lexical_overlap: float = 0.1,
    max_chars_per_snippet: int = 280,
    include_icd_suggestions: bool = False,
    icd_path: str = DEFAULT_ICD_CODES_PATH,
    icd_top_k: int = 3,
) -> str:
    if vectorstore is None:
        return ""

    retrieval_queries = build_retrieval_queries(query, max_queries=max_queries)
    pool_k = max(retrieve_k * RETRIEVAL_POOL_K_MULTIPLIER, RETRIEVAL_POOL_K_MIN)
    intent = classify_retrieval_intent(query)
    medication_focused = intent["medication_focused"]
    lab_focused = intent["lab_focused"]
    symptom_focused = intent["symptom_focused"]
    ddi_focused = intent["ddi_focused"]
    clinical_query = symptom_focused or medication_focused or lab_focused
    lab_only = lab_focused and not symptom_focused and not medication_focused
    query_med_terms = extract_query_medication_terms(query)
    allow_ddi = ddi_focused
    symptom_terms = extract_symptom_terms_from_text(query)
    query_norm = normalize_symptom_key(query)
    query_is_english = _looks_english(query)
    symptom_terms_norm = {normalize_symptom_key(term) for term in symptom_terms if term}
    query_med_terms_norm = {normalize_symptom_key(term) for term in query_med_terms if term}

    def _threaded_search(rq: str) -> tuple[str, list, bool]:
        try:
            return rq, similarity_search_with_optional_filter(vectorstore, rq, k=pool_k), False
        except Exception:
            return rq, [], False

    with ThreadPoolExecutor(max_workers=max_queries) as executor:
        all_results = list(executor.map(_threaded_search, retrieval_queries))

    lexical_raw = _lexical_search_from_vectorstore(
        query=query,
        vectorstore=vectorstore,
        k=max(pool_k * 2, 24),
        query_is_english=query_is_english,
    )
    if lexical_raw:
        all_results.append((query, lexical_raw, True))

    targeted_filters = [{"source": "clinical_lab_facts.csv"}] if lab_only else []
    if symptom_focused:
        targeted_filters.append({"doc_type": "drug_monograph"})
    if allow_ddi:
        targeted_filters.append({"source": "DDI_data_clean.csv"})

    allowed_monograph_sections = {
        "indications", "indications & usage", "indications and usage", "clinical",
        "usage", "uses", "therapeutic", "overview", "summary",
    }

    def _monograph_allowed(doc) -> bool:
        if doc_category(doc) != "drug_monograph":
            return True

        section = normalize_symptom_key(str(doc.metadata.get("section", "")))
        if section in allowed_monograph_sections:
            return True

        drug_name = normalize_symptom_key(str(doc.metadata.get("drug", "")))
        return bool(drug_name and drug_name in query_norm)

    def _matches_query_focus(doc) -> bool:
        if not symptom_focused:
            return True

        text_norm = normalize_symptom_key(doc.page_content or "")
        if any(term and term in text_norm for term in symptom_terms_norm):
            return True
        if any(term and term in text_norm for term in query_med_terms_norm):
            return True

        drug_name = normalize_symptom_key(str(doc.metadata.get("drug", "")))
        if drug_name and drug_name in query_norm:
            return True

        return False

    targeted_k = max(RETRIEVAL_TARGETED_K_MIN, retrieve_k // 2)
    for rq in retrieval_queries[:2]:
        for where in targeted_filters:
            raw = similarity_search_with_optional_filter(vectorstore, rq, k=targeted_k, where=where)
            if raw:
                all_results.append((rq, raw, True))

    merged: dict[str, dict[str, Any]] = {}

    for rq, raw, is_targeted in all_results:
        if not raw:
            continue

        try:
            first_score = float(raw[0][1])
            last_score = float(raw[-1][1])
            lower_is_better = first_score <= last_score

            score_values = [float(s) for _, s in raw]
            s_min, s_max = min(score_values), max(score_values)
            s_span = (s_max - s_min) or 1.0

            docs_with_semantic = []
            for rank, (doc, score) in enumerate(raw):
                score = float(score)
                if lower_is_better:
                    score_norm = (s_max - score) / s_span
                else:
                    score_norm = (score - s_min) / s_span

                rank_rrf = 1.0 / (rank + RETRIEVAL_RRF_K)
                semantic = RETRIEVAL_SCORE_NORM_WEIGHT * score_norm + RETRIEVAL_RRF_WEIGHT * rank_rrf
                docs_with_semantic.append((doc, semantic))
        except Exception:
            docs_with_semantic = [(doc, 1.0 / (rank + 1.0)) for rank, (doc, _) in enumerate(raw)]

        for doc, semantic in docs_with_semantic:
            # Filter out clearly non-English KB entries when the query is English
            if query_is_english and not _looks_english(doc.page_content):
                continue
            if clinical_query and not _looks_clinical_enough(doc.page_content, doc.metadata):
                continue
            if not _matches_query_focus(doc):
                continue

            # Boost documents that explicitly mention medications present in the query
            try:
                drug_meta = normalize_symptom_key(str(doc.metadata.get("drug", "")))
            except Exception:
                drug_meta = ""
            if drug_meta and drug_meta in query_norm:
                semantic += 0.9
            else:
                # also check page content for medication mentions
                if query_med_terms:
                    content_norm = normalize_symptom_key(doc.page_content or "")
                    for qmt in query_med_terms:
                        qn = normalize_symptom_key(str(qmt))
                        if qn and qn in content_norm:
                            semantic += 0.6
                            break
            lex = lexical_overlap_ratio(rq, doc.page_content)
            if not is_targeted and lex < min_lexical_overlap:
                if not (symptom_focused and doc_category(doc) in {"drug_monograph", "clinical_text"}):
                    continue

            if symptom_focused and not _monograph_allowed(doc):
                continue

            source = doc.metadata.get("source", "unknown")
            row = doc.metadata.get("row", -1)
            line_index = doc.metadata.get("line_index", -1)
            key = f"{source}|{row}|{line_index}|{hash(doc.page_content)}"

            if key not in merged:
                merged[key] = {
                    "doc": doc,
                    "hits": 1,
                    "semantic_sum": semantic,
                    "lex_max": lex,
                }
            else:
                item = merged[key]
                item["hits"] += 1
                item["semantic_sum"] += semantic
                item["lex_max"] = max(item["lex_max"], lex)
    # Compute BM25 scores across merged docs to compensate for weak embeddings
    if merged:
        docs_list = list(merged.values())
        corpus_tokens = [_tokenize_bm25(d["doc"].page_content or "") for d in docs_list]
        # local candidate-level BM25 reranker (kept even with corpus-level lexical search)
        N = len(corpus_tokens)
        df: dict[str, int] = {}
        lens = [len(d) for d in corpus_tokens]
        for doc_tokens in corpus_tokens:
            seen = set(doc_tokens)
            for tok in seen:
                df[tok] = df.get(tok, 0) + 1
        idf = {tok: math.log((N - dfi + 0.5) / (dfi + 0.5) + 1.0) for tok, dfi in df.items()}
        avgdl = (sum(lens) / N) if N > 0 else 0.0
        query_tokens = _tokenize_bm25(query)
        bm25_vals = []
        for doc_tokens in corpus_tokens:
            tf_local: dict[str, int] = {}
            for tok in doc_tokens:
                tf_local[tok] = tf_local.get(tok, 0) + 1
            bm25_vals.append(float(_bm25_score_from_tf(query_tokens, tf_local, idf, len(doc_tokens), avgdl)))
        max_bm = max(bm25_vals) if bm25_vals else 0.0
        for item, bm in zip(docs_list, bm25_vals):
            # normalized into 0..1
            item["bm25"] = (bm / max_bm) if max_bm > 0 else 0.0

        # detect weak semantic signal (low variance) and adjust weights later
        sem_vals = [d["semantic_sum"] / d["hits"] if d["hits"] else 0.0 for d in docs_list]
        try:
            import statistics

            sem_std = statistics.pstdev(sem_vals) if sem_vals else 0.0
            sem_mean = statistics.mean(sem_vals) if sem_vals else 0.0
        except Exception:
            sem_std = 0.0
            sem_mean = 0.0
        merged_sem_stats = {"std": sem_std, "mean": sem_mean}
    else:
        merged_sem_stats = {"std": 0.0, "mean": 0.0}
    
    if not merged:
        fallback_merged: dict[str, dict[str, Any]] = {}

        def _allow_fallback_category(cat: str) -> bool:
            if cat == "lab_reference" and not lab_only:
                return False
            if cat == "drug_interactions" and not allow_ddi:
                return False
            return True

        for rq, raw, _is_targeted in all_results:
            if not raw:
                continue

            for rank, (doc, _score) in enumerate(raw):
                if clinical_query and not _looks_clinical_enough(doc.page_content, doc.metadata):
                    continue
                if not _matches_query_focus(doc):
                    continue
                if not _allow_fallback_category(doc_category(doc)):
                    continue
                key = f"{doc.metadata.get('source', 'unknown')}|{doc.metadata.get('row', -1)}|{doc.metadata.get('line_index', -1)}|{hash(doc.page_content)}"
                if key in fallback_merged:
                    continue

                fallback_merged[key] = {
                    "doc": doc,
                    "hits": 1,
                    "semantic_sum": 1.0 / (rank + 1.0),
                    "lex_max": lexical_overlap_ratio(rq, doc.page_content),
                }

        if not fallback_merged:
            for rq, raw, _is_targeted in all_results:
                if not raw:
                    continue

                for rank, (doc, _score) in enumerate(raw):
                    if clinical_query and not _looks_clinical_enough(doc.page_content, doc.metadata):
                        continue
                    if not _matches_query_focus(doc):
                        continue
                    if not _allow_fallback_category(doc_category(doc)):
                        continue
                    key = f"{doc.metadata.get('source', 'unknown')}|{doc.metadata.get('row', -1)}|{doc.metadata.get('line_index', -1)}|{hash(doc.page_content)}"
                    if key in fallback_merged:
                        continue

                    fallback_merged[key] = {
                        "doc": doc,
                        "hits": 1,
                        "semantic_sum": 1.0 / (rank + 1.0),
                        "lex_max": lexical_overlap_ratio(rq, doc.page_content),
                    }

        if not fallback_merged:
            return ""
        merged = fallback_merged

    # adjust weights when query is clearly English (helps when embeddings are weak)
    sem_w = RETRIEVAL_SEMANTIC_WEIGHT * (0.5 if query_is_english else 1.0)
    bm25_w = RETRIEVAL_BM25_WEIGHT
    if query_is_english:
        bm25_w = max(bm25_w, 0.6)

    # If semantic scores show very low variance (hash embeddings), strongly prefer BM25
    if merged_sem_stats.get("std", 0.0) < 0.01:
        sem_w = RETRIEVAL_SEMANTIC_WEIGHT * 0.05
        bm25_w = max(bm25_w, 0.9)

    def _pre_score(item: dict) -> float:
        return (
            sem_w * (item["semantic_sum"] / item["hits"])
            + RETRIEVAL_LEXICAL_WEIGHT * item["lex_max"]
            + bm25_w * item.get("bm25", 0.0)
        )

    if len(merged) > RETRIEVAL_MAX_MERGED_DOCS:
        trimmed = sorted(merged.values(), key=_pre_score, reverse=True)[:RETRIEVAL_MAX_MERGED_DOCS]
        merged = {id(item["doc"]): item for item in trimmed}

    max_hits = max(item["hits"] for item in merged.values())

    ranked = sorted(
        merged.values(),
        key=lambda item: (
            sem_w * (item["semantic_sum"] / item["hits"])
            + RETRIEVAL_LEXICAL_WEIGHT * item["lex_max"]
            + bm25_w * item.get("bm25", 0.0)
            + RETRIEVAL_HITS_WEIGHT * (item["hits"] / max_hits)
        ),
        reverse=True,
    )

    def _rank_score(item: dict[str, Any]) -> float:
        return (
            sem_w * (item["semantic_sum"] / item["hits"])
            + RETRIEVAL_LEXICAL_WEIGHT * item["lex_max"]
            + bm25_w * item.get("bm25", 0.0)
            + RETRIEVAL_HITS_WEIGHT * (item["hits"] / max_hits)
        )

    snippets: list[str] = []
    seen_text: set[str] = set()
    selected_records: list[dict[str, Any]] = []
    max_drug_monographs = max(2, final_k // 2) if medication_focused else 1
    max_lab_references = 1 if (lab_focused and symptom_focused) else (2 if lab_focused else 0)

    category_top: dict[str, dict] = {}
    for item in ranked:
        cat = doc_category(item["doc"])
        if cat not in category_top:
            category_top[cat] = item

    def _category_priority(cat: str) -> float:
        if symptom_focused:
            if cat == "clinical_text":
                return CATEGORY_PRIORITY_SYMPTOM_CLINICAL
            if cat == "lab_reference":
                return CATEGORY_PRIORITY_SYMPTOM_LAB
            if cat == "drug_interactions":
                return CATEGORY_PRIORITY_SYMPTOM_DDI
        if medication_focused and cat == "drug_monograph":
            return CATEGORY_PRIORITY_MED_MONOGRAPH
        return 0.0

    category_order = sorted(
        category_top.keys(),
        key=lambda cat: _rank_score(category_top[cat]) + _category_priority(cat),
        reverse=True,
    )

    selected_categories = []
    for cat in category_order:
        item = category_top[cat]
        if cat == "drug_monograph":
            existing_drug = sum(1 for rec in selected_records if rec["cat"] == "drug_monograph")
            if existing_drug >= max_drug_monographs:
                continue
        if cat == "lab_reference":
            if not lab_focused:
                continue
            existing_lab = sum(1 for rec in selected_records if rec["cat"] == "lab_reference")
            if existing_lab >= max_lab_references:
                continue
        if cat == "drug_interactions" and not allow_ddi:
            continue

        snippet = truncate_snippet(item["doc"].page_content, max_chars_per_snippet)
        key = snippet.lower()
        if not snippet or key in seen_text:
            continue

        seen_text.add(key)
        snippets.append(snippet)
        selected_records.append({"item": item, "cat": cat, "snippet": snippet, "score": _rank_score(item)})
        selected_categories.append(cat)
        if len(snippets) >= final_k:
            break

    if len(snippets) < final_k:
        max_per_category = max(RETRIEVAL_MAX_PER_CATEGORY_MIN, (final_k + 1) // 2)
        selected_doc_ids = {id(category_top[cat]["doc"]) for cat in selected_categories}

        category_selected = {}
        for cat in selected_categories:
            category_selected[cat] = category_selected.get(cat, 0) + 1

        for item in ranked:
            if len(snippets) >= final_k:
                break

            doc = item["doc"]
            if id(doc) in selected_doc_ids:
                continue

            cat = doc_category(doc)
            if cat == "drug_monograph":
                if category_selected.get(cat, 0) >= max_drug_monographs:
                    continue
            if cat == "lab_reference":
                if not lab_focused:
                    continue
                if category_selected.get(cat, 0) >= max_lab_references:
                    continue
            if cat == "drug_interactions" and not allow_ddi:
                continue
            if category_selected.get(cat, 0) >= max_per_category:
                continue

            snippet = truncate_snippet(doc.page_content, max_chars_per_snippet)
            key = snippet.lower()
            if not snippet or key in seen_text:
                continue

            seen_text.add(key)
            snippets.append(snippet)
            selected_doc_ids.add(id(doc))
            category_selected[cat] = category_selected.get(cat, 0) + 1
            selected_records.append({"item": item, "cat": cat, "snippet": snippet, "score": _rank_score(item)})

    if not selected_records:
        for item in ranked:
            cat = doc_category(item["doc"])
            if cat == "drug_interactions" and not allow_ddi:
                continue
            snippet = truncate_snippet(item["doc"].page_content, max_chars_per_snippet)
            key = snippet.lower()
            if not snippet or key in seen_text:
                continue
            selected_records.append({"item": item, "cat": cat, "snippet": snippet, "score": _rank_score(item)})
            seen_text.add(key)
            if len(selected_records) >= max(1, final_k // 2):
                break

    if final_k >= 3 and allow_ddi:
        best_ddi = None
        for item in ranked:
            if doc_category(item["doc"]) != "drug_interactions":
                continue
            if query_med_terms:
                pair_terms = extract_ddi_pair_terms(item["doc"])
                if pair_terms and not (pair_terms.intersection(query_med_terms)):
                    continue
            best_ddi = item
            break

        has_ddi = any(rec["cat"] == "drug_interactions" for rec in selected_records)

        if best_ddi is not None and not has_ddi:
            ddi_snippet = truncate_snippet(best_ddi["doc"].page_content, max_chars_per_snippet)
            ddi_key = ddi_snippet.lower()
            if ddi_snippet and ddi_key not in seen_text:
                ddi_record = {
                    "item": best_ddi,
                    "cat": "drug_interactions",
                    "snippet": ddi_snippet,
                    "score": _rank_score(best_ddi),
                }

                if len(selected_records) < final_k:
                    selected_records.append(ddi_record)
                    seen_text.add(ddi_key)
                else:
                    replace_candidates = [
                        rec for rec in selected_records if rec["cat"] != "drug_interactions"
                    ]
                    if replace_candidates:
                        monograph_candidates = [rec for rec in replace_candidates if rec["cat"] == "drug_monograph"]
                        target_pool = monograph_candidates if monograph_candidates else replace_candidates
                        to_replace = min(target_pool, key=lambda rec: rec["score"])
                        selected_records.remove(to_replace)
                        selected_records.append(ddi_record)
                        seen_text.discard(to_replace["snippet"].lower())
                        seen_text.add(ddi_key)

    if not selected_records and lab_only:
        for rq in retrieval_queries[:2]:
            raw = similarity_search_with_optional_filter(vectorstore, rq, k=max(4, retrieve_k // 2), where={"source": "clinical_lab_facts.csv"})
            if not raw:
                continue
            for rank, (doc, score) in enumerate(raw):
                if doc_category(doc) != "lab_reference":
                    continue
                snippet = truncate_snippet(doc.page_content, max_chars_per_snippet)
                key = snippet.lower()
                if not snippet or key in seen_text:
                    continue
                selected_records.append({"item": {"doc": doc}, "cat": "lab_reference", "snippet": snippet, "score": float(score) if isinstance(score, (int, float)) else 0.0})
                seen_text.add(key)
                if len(selected_records) >= max(1, final_k // 2):
                    break
            if selected_records:
                break

    if not selected_records:
        for item in ranked:
            snippet = truncate_snippet(item["doc"].page_content, max_chars_per_snippet)
            key = snippet.lower()
            if not snippet or key in seen_text:
                continue
            selected_records.append({"item": item, "cat": doc_category(item["doc"]), "snippet": snippet, "score": _rank_score(item)})
            seen_text.add(key)
            if len(selected_records) >= 1:
                break

    selected_records.sort(key=lambda rec: rec["score"], reverse=True)

    def _symptom_bonus(text: str) -> float:
        if not symptom_terms:
            return 0.0
        norm = normalize_symptom_key(text)
        hits = sum(1 for term in symptom_terms if normalize_symptom_key(term) in norm)
        return min(SYMPTOM_BONUS_MAX, SYMPTOM_BONUS_PER_HIT * hits)

    def _section_penalty(rec: dict[str, Any]) -> float:
        if not symptom_focused or rec.get("cat") != "drug_monograph":
            return 0.0
        doc = rec.get("item", {}).get("doc")
        if not doc:
            return 0.0
        section = normalize_symptom_key(str(doc.metadata.get("section", "")))
        if section in {"warnings", "dosage", "dosage and administration", "adverse reactions"}:
            return SECTION_PENALTY
        return 0.0

    def _category_adjustment(rec: dict[str, Any]) -> float:
        cat = rec.get("cat")
        if symptom_focused:
            if cat == "clinical_text":
                return CATEGORY_ADJUST_SYMPTOM_CLINICAL
            if cat == "drug_monograph":
                return CATEGORY_ADJUST_SYMPTOM_MONOGRAPH
            if cat == "lab_reference":
                return CATEGORY_ADJUST_SYMPTOM_LAB
            if cat == "drug_interactions":
                return CATEGORY_ADJUST_SYMPTOM_DDI
        if medication_focused and cat == "drug_monograph":
            return CATEGORY_ADJUST_MED_MONOGRAPH
        return 0.0

    def _source_bonus(rec: dict[str, Any]) -> float:
        doc = rec.get("item", {}).get("doc")
        if not doc:
            return 0.0
        source = normalize_symptom_key(str(doc.metadata.get("source", "")))
        if "symptom" in source or "summary" in source:
            return SOURCE_BONUS_SYMPTOM if symptom_focused else SOURCE_BONUS_GENERAL
        return 0.0

    selected_records.sort(
        key=lambda rec: (
            rec["score"]
            + _symptom_bonus(rec["snippet"])
            + _category_adjustment(rec)
            + _source_bonus(rec)
            - _section_penalty(rec)
        ),
        reverse=True,
    )
    snippets = [rec["snippet"] for rec in selected_records[:final_k]]

    context = "\n\n".join(snippets)

    if include_icd_suggestions:
        codes = suggest_icd_codes_local(query, icd_path=icd_path, top_k=icd_top_k)
        if codes:
            lines = ["Suggested ICD-10 codes (local lookup):"]
            for item in codes:
                code = item.get("code", "")
                desc = item.get("description", "")
                symptom = item.get("matched_symptom", "")
                score = item.get("score", "")
                if code and desc:
                    lines.append(f"- {code}: {desc} (matched symptom: {symptom}, score={score})")
            if len(lines) > 1:
                context = f"{context}\n\n" + "\n".join(lines) if context else "\n".join(lines)

    if not context and ranked:
        if medication_focused:
            preferred_categories = ["drug_monograph", "drug_interactions", "clinical_text", "csv_reference", "lab_reference"]
        elif symptom_focused:
            preferred_categories = ["clinical_text", "csv_reference", "drug_monograph", "lab_reference", "drug_interactions"]
        elif lab_only:
            preferred_categories = ["lab_reference", "csv_reference", "clinical_text", "drug_monograph", "drug_interactions"]
        else:
            preferred_categories = ["clinical_text", "csv_reference", "drug_monograph", "lab_reference", "drug_interactions"]
        chosen_item = None

        for preferred_category in preferred_categories:
            for item in ranked:
                if doc_category(item["doc"]) == preferred_category:
                    chosen_item = item
                    break
            if chosen_item is not None:
                break

        if chosen_item is None:
            chosen_item = ranked[0]

        chosen_cat = doc_category(chosen_item["doc"])
        if (chosen_cat == "lab_reference" and not lab_only) or (chosen_cat == "drug_interactions" and not allow_ddi):
            return ""

        context = truncate_snippet(chosen_item["doc"].page_content, max_chars_per_snippet)

    return context
