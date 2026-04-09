from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .config import DEFAULT_ICD_CODES_PATH
from .icd import suggest_icd_codes_local
from .text_processing import (
    build_retrieval_queries,
    doc_category,
    extract_ddi_pair_terms,
    extract_query_medication_terms,
    lexical_overlap_ratio,
    query_likely_medication_focused,
    transcript_mentions_labs,
    truncate_snippet,
)


def similarity_search_with_optional_filter(vectorstore, query: str, k: int, where: Optional[dict] = None):
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
    vectorstore,
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
    pool_k = max(retrieve_k * 2, 12)
    medication_focused = query_likely_medication_focused(query)
    query_med_terms = extract_query_medication_terms(query)
    allow_ddi = medication_focused or bool(query_med_terms)

    def _threaded_search(rq):
        try:
            return rq, similarity_search_with_optional_filter(vectorstore, rq, k=pool_k), False
        except Exception:
            return rq, [], False

    with ThreadPoolExecutor(max_workers=max_queries) as executor:
        all_results = list(executor.map(_threaded_search, retrieval_queries))

    targeted_filters = [{"source": "clinical_lab_facts.csv"}]
    if allow_ddi:
        targeted_filters.append({"source": "DDI_data_clean.csv"})

    targeted_k = max(4, retrieve_k // 2)
    for rq in retrieval_queries[:2]:
        for where in targeted_filters:
            raw = similarity_search_with_optional_filter(vectorstore, rq, k=targeted_k, where=where)
            if raw:
                all_results.append((rq, raw, True))

    merged = {}

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

                rank_rrf = 1.0 / (rank + 1.0)
                semantic = 0.70 * score_norm + 0.30 * rank_rrf
                docs_with_semantic.append((doc, semantic))
        except Exception:
            docs_with_semantic = [(doc, 1.0 / (rank + 1.0)) for rank, (doc, _) in enumerate(raw)]

        for doc, semantic in docs_with_semantic:
            lex = lexical_overlap_ratio(rq, doc.page_content)
            if not is_targeted and lex < min_lexical_overlap:
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

    if not merged:
        return ""

    max_hits = max(item["hits"] for item in merged.values())

    ranked = sorted(
        merged.values(),
        key=lambda item: (
            0.65 * (item["semantic_sum"] / item["hits"])
            + 0.25 * item["lex_max"]
            + 0.10 * (item["hits"] / max_hits)
        ),
        reverse=True,
    )

    def _rank_score(item: dict) -> float:
        return (
            0.65 * (item["semantic_sum"] / item["hits"])
            + 0.25 * item["lex_max"]
            + 0.10 * (item["hits"] / max_hits)
        )

    snippets = []
    seen_text = set()
    selected_records: list[dict] = []
    max_drug_monographs = max(2, final_k // 2) if medication_focused else 1
    max_lab_references = 2 if transcript_mentions_labs(query) else 1

    category_top: dict[str, dict] = {}
    for item in ranked:
        cat = doc_category(item["doc"])
        if cat not in category_top:
            category_top[cat] = item

    category_order = sorted(
        category_top.keys(),
        key=lambda cat: _rank_score(category_top[cat]),
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
        max_per_category = max(2, (final_k + 1) // 2)
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

    selected_records.sort(key=lambda rec: rec["score"], reverse=True)
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

    return context
